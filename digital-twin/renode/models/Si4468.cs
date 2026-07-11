// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Command-level Si4468 model with persistent properties and a deterministic
    /// RF scene. GPIO input 0 is SDN (active high); CTS is driven high whenever
    /// the modeled part is ready.
    /// </summary>
    public sealed class Si4468 : ISPIPeripheral, IGPIOReceiver
    {
        public Si4468()
        {
            CTS = new GPIO();
            Reset();
        }

        public GPIO CTS { get; }

        public double ReceiverFrequencyHz { get; private set; }

        public double TunedInputFrequencyHz { get; private set; }

        public double FrontEndAttenuationDb { get; private set; }

        public double NoiseFloorDbm { get; private set; }

        public byte LastRssiRaw { get; private set; }

        public byte State => state;

        public ulong CommandCount { get; private set; }

        public int ToneCount => tones.Count;

        public ulong RssiSampleCount { get; private set; }

        public byte MinimumRssiRaw { get; private set; }

        public byte PeakRssiRaw { get; private set; }

        public void Reset()
        {
            transaction.Clear();
            pendingResponse = Array.Empty<byte>();
            properties.Clear();
            tones.Clear();
            state = StateReady;
            channel = 0;
            shutdown = true;
            fixedRssi = null;
            ReceiverFrequencyHz = 0;
            TunedInputFrequencyHz = 0;
            FrontEndAttenuationDb = 0;
            NoiseFloorDbm = -110.0;
            LastRssiRaw = DbmToRaw(NoiseFloorDbm);
            CommandCount = 0;
            ResetRssiStatistics();
            CTS.Unset();
        }

        public void OnGPIO(int number, bool value)
        {
            if(number != ShutdownInput)
            {
                throw new ArgumentOutOfRangeException(nameof(number));
            }

            shutdown = value;
            if(value)
            {
                transaction.Clear();
                pendingResponse = Array.Empty<byte>();
                state = StateReady;
                CTS.Unset();
            }
            else
            {
                CTS.Set();
            }
        }

        public byte Transmit(byte data)
        {
            if(shutdown)
            {
                return 0;
            }

            if(transaction.Count == 0)
            {
                transaction.Add(data);
                return 0;
            }

            var command = transaction[0];
            if(command == ReadCommandBuffer)
            {
                transaction.Add(data);
                var responseIndex = transaction.Count - 3;
                if(responseIndex < 0)
                {
                    return ClearToSend;
                }
                return responseIndex < pendingResponse.Length
                    ? pendingResponse[responseIndex]
                    : (byte)0;
            }

            if(IsFastResponseRegister(command))
            {
                transaction.Add(data);
                return transaction.Count == 2 ? ReadFastResponse(command) : (byte)0;
            }

            transaction.Add(data);
            return 0;
        }

        public void FinishTransmission()
        {
            if(transaction.Count == 0)
            {
                return;
            }
            var command = transaction[0];
            if(command != ReadCommandBuffer && !IsFastResponseRegister(command))
            {
                ProcessCommand(transaction.ToArray());
            }
            transaction.Clear();
        }

        public void SetFrontEndState(double tunedInputFrequencyHz, double attenuationDb)
        {
            TunedInputFrequencyHz = Math.Max(0, tunedInputFrequencyHz);
            FrontEndAttenuationDb = Math.Max(0, attenuationDb);
        }

        public void SetNoiseFloorDbm(double value)
        {
            NoiseFloorDbm = value;
        }

        public void SetFixedRssi(int raw)
        {
            fixedRssi = (byte)Math.Max(0, Math.Min(255, raw));
        }

        public void ClearFixedRssi()
        {
            fixedRssi = null;
        }

        public void AddTone(double frequencyHz, double powerDbm, double widthHz = 100000.0)
        {
            if(frequencyHz < 0 || widthHz <= 0)
            {
                throw new ArgumentOutOfRangeException();
            }
            tones.Add(new Tone(frequencyHz, powerDbm, widthHz));
        }

        public void ClearTones()
        {
            tones.Clear();
        }

        public void ResetRssiStatistics()
        {
            RssiSampleCount = 0;
            MinimumRssiRaw = byte.MaxValue;
            PeakRssiRaw = byte.MinValue;
        }

        public byte GetProperty(int group, int property)
        {
            var key = MakePropertyKey((byte)group, (byte)property);
            return properties.TryGetValue(key, out var value) ? value : (byte)0;
        }

        private void ProcessCommand(byte[] request)
        {
            CommandCount++;
            pendingResponse = Array.Empty<byte>();
            switch(request[0])
            {
                case PowerUp:
                    state = StateReady;
                    CTS.Set();
                    break;
                case PartInfo:
                    // CHIPREV, PART=0x4468, PBUILD, ID, CUSTOMER, ROMID.
                    pendingResponse = new byte[] { 0x11, 0x44, 0x68, 0x00, 0x00, 0x01, 0x00, 0x06 };
                    break;
                case FunctionInfo:
                    pendingResponse = new byte[] { 0x03, 0x00, 0x00, 0x00, 0x00, 0x01 };
                    break;
                case SetProperty:
                    SetProperties(request);
                    break;
                case GetPropertyCommand:
                    GetProperties(request);
                    break;
                case GpioPinConfiguration:
                    pendingResponse = new byte[7];
                    break;
                case FifoInfo:
                    pendingResponse = new byte[] { 0, 0 };
                    break;
                case GetInterruptStatus:
                    pendingResponse = new byte[8];
                    break;
                case RequestDeviceState:
                    pendingResponse = new byte[] { state, channel };
                    break;
                case ChangeState:
                    if(request.Length > 1)
                    {
                        state = request[1];
                    }
                    break;
                case StartReceive:
                    channel = request.Length > 1 ? request[1] : (byte)0;
                    state = StateReceive;
                    break;
                case StartTransmit:
                    channel = request.Length > 1 ? request[1] : (byte)0;
                    state = StateTransmit;
                    break;
                case GetModemStatus:
                    var rssi = SampleRssi();
                    pendingResponse = new byte[] { 0, 0, rssi, rssi, rssi, rssi, 0, 0 };
                    break;
                case GetAdcReading:
                    // 25 C using firmware's T=(899*raw/4096)-293 equation.
                    pendingResponse = new byte[] { 0, 0, 0x08, 0x00, 0x05, 0xA8, 0, 0 };
                    break;
                default:
                    break;
            }
        }

        private void SetProperties(byte[] request)
        {
            if(request.Length < 4)
            {
                return;
            }
            var group = request[1];
            var count = request[2];
            var start = request[3];
            for(var i = 0; i < count && 4 + i < request.Length; ++i)
            {
                properties[MakePropertyKey(group, (byte)(start + i))] = request[4 + i];
            }
            RecalculateReceiverFrequency();
        }

        private void GetProperties(byte[] request)
        {
            if(request.Length < 4)
            {
                return;
            }
            var group = request[1];
            var count = request[2];
            var start = request[3];
            pendingResponse = new byte[count];
            for(var i = 0; i < count; ++i)
            {
                properties.TryGetValue(MakePropertyKey(group, (byte)(start + i)), out pendingResponse[i]);
            }
        }

        private void RecalculateReceiverFrequency()
        {
            if(!TryGetProperty(0x40, 0x00, out var integer)
                || !TryGetProperty(0x40, 0x01, out var fraction2)
                || !TryGetProperty(0x40, 0x02, out var fraction1)
                || !TryGetProperty(0x40, 0x03, out var fraction0)
                || !TryGetProperty(0x20, 0x51, out var bandValue))
            {
                return;
            }

            var fraction = ((uint)fraction2 << 16) | ((uint)fraction1 << 8) | fraction0;
            var band = bandValue & 0x7;
            var divider = band switch
            {
                0 => 4.0,
                1 => 10.0,
                2 => 8.0,
                3 => 12.0,
                5 => 24.0,
                _ => 4.0,
            };
            ReceiverFrequencyHz = (integer + fraction / 524288.0)
                * (2.0 * ReferenceFrequencyHz) / divider;
        }

        private byte SampleRssi()
        {
            if(fixedRssi.HasValue)
            {
                return RecordRssi(fixedRssi.Value);
            }

            var level = NoiseFloorDbm;
            foreach(var tone in tones)
            {
                var delta = Math.Abs(TunedInputFrequencyHz - tone.FrequencyHz);
                var halfWidth = tone.WidthHz / 2.0;
                var rolloff = delta <= halfWidth
                    ? 0.0
                    : 20.0 * Math.Log10(1.0 + (delta - halfWidth) / halfWidth);
                level = Math.Max(level, tone.PowerDbm - rolloff - FrontEndAttenuationDb);
            }
            return RecordRssi(DbmToRaw(level));
        }

        private byte RecordRssi(byte value)
        {
            LastRssiRaw = value;
            RssiSampleCount++;
            MinimumRssiRaw = Math.Min(MinimumRssiRaw, value);
            PeakRssiRaw = Math.Max(PeakRssiRaw, value);
            return LastRssiRaw;
        }

        private byte ReadFastResponse(byte command)
        {
            switch(command)
            {
                case ReadFastResponseA:
                    return SampleRssi();
                case ReadFastResponseB:
                    return state;
                default:
                    return 0;
            }
        }

        private bool TryGetProperty(byte group, byte property, out byte value)
        {
            return properties.TryGetValue(MakePropertyKey(group, property), out value);
        }

        private static ushort MakePropertyKey(byte group, byte property)
        {
            return (ushort)((group << 8) | property);
        }

        private static bool IsFastResponseRegister(byte command)
        {
            return command == ReadFastResponseA || command == ReadFastResponseB
                || command == ReadFastResponseC || command == ReadFastResponseD;
        }

        private static byte DbmToRaw(double dbm)
        {
            return (byte)Math.Max(0, Math.Min(255, (int)Math.Round(2.0 * (dbm + 120.0))));
        }

        private sealed class Tone
        {
            public Tone(double frequencyHz, double powerDbm, double widthHz)
            {
                FrequencyHz = frequencyHz;
                PowerDbm = powerDbm;
                WidthHz = widthHz;
            }

            public double FrequencyHz { get; }
            public double PowerDbm { get; }
            public double WidthHz { get; }
        }

        private readonly List<byte> transaction = new List<byte>();
        private readonly Dictionary<ushort, byte> properties = new Dictionary<ushort, byte>();
        private readonly List<Tone> tones = new List<Tone>();
        private byte[] pendingResponse;
        private byte state;
        private byte channel;
        private byte? fixedRssi;
        private bool shutdown;

        private const double ReferenceFrequencyHz = 30000000.0;
        private const int ShutdownInput = 0;
        private const byte ClearToSend = 0xFF;
        private const byte StateReady = 0x03;
        private const byte StateTransmit = 0x07;
        private const byte StateReceive = 0x08;
        private const byte PartInfo = 0x01;
        private const byte PowerUp = 0x02;
        private const byte FunctionInfo = 0x10;
        private const byte SetProperty = 0x11;
        private const byte GetPropertyCommand = 0x12;
        private const byte GpioPinConfiguration = 0x13;
        private const byte GetAdcReading = 0x14;
        private const byte FifoInfo = 0x15;
        private const byte GetInterruptStatus = 0x20;
        private const byte GetModemStatus = 0x22;
        private const byte StartTransmit = 0x31;
        private const byte StartReceive = 0x32;
        private const byte RequestDeviceState = 0x33;
        private const byte ChangeState = 0x34;
        private const byte ReadCommandBuffer = 0x44;
        private const byte ReadFastResponseA = 0x50;
        private const byte ReadFastResponseB = 0x51;
        private const byte ReadFastResponseC = 0x53;
        private const byte ReadFastResponseD = 0x57;
    }
}
