// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Text;
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

        public double LocalOscillatorFrequencyHz { get; private set; }

        public double MinimumTunedInputFrequencyHz { get; private set; }

        public double MaximumTunedInputFrequencyHz { get; private set; }

        public double MinimumLocalOscillatorFrequencyHz { get; private set; }

        public double MaximumLocalOscillatorFrequencyHz { get; private set; }

        public double NoiseFloorDbm { get; private set; }

        public bool CalibrationLoopbackConnected { get; private set; }

        public bool CalibrationOutputEnabled { get; private set; }

        public double CalibrationFrequencyHz { get; private set; }

        public double CalibrationPowerDbm { get; private set; }

        public int SelfTestFixture { get; private set; }

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
            LocalOscillatorFrequencyHz = 0;
            NoiseFloorDbm = -110.0;
            CalibrationLoopbackConnected = false;
            CalibrationOutputEnabled = false;
            CalibrationFrequencyHz = 0;
            CalibrationPowerDbm = DefaultCalibrationPowerDbm;
            calibrationGpioMode = 0;
            trackingIfCandidateHz = null;
            trackingIfCenterHz = null;
            SelfTestFixture = 0;
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

        public void SetLocalOscillatorFrequency(double frequencyHz)
        {
            LocalOscillatorFrequencyHz = Math.Max(0, frequencyHz);
        }

        public void SetNoiseFloorDbm(double value)
        {
            NoiseFloorDbm = value;
        }

        public void SetCalibrationLoopback(bool connected)
        {
            CalibrationLoopbackConnected = connected;
        }

        public void SetCalibrationPowerDbm(double value)
        {
            if(value < -120.0 || value > 0.0)
            {
                throw new ArgumentOutOfRangeException(nameof(value));
            }
            CalibrationPowerDbm = value;
        }

        public void SetSelfTestFixture(int oneBasedTest)
        {
            if(oneBasedTest < 0 || oneBasedTest > 14)
            {
                throw new ArgumentOutOfRangeException(nameof(oneBasedTest));
            }
            SelfTestFixture = oneBasedTest;
            trackingIfCandidateHz = null;
            trackingIfCenterHz = null;
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
            MinimumTunedInputFrequencyHz = double.MaxValue;
            MaximumTunedInputFrequencyHz = double.MinValue;
            MinimumLocalOscillatorFrequencyHz = double.MaxValue;
            MaximumLocalOscillatorFrequencyHz = double.MinValue;
            frequencyTrace.Clear();
            frequencyTraceNext = 0;
            frequencyTraceWrapped = false;
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
                    if(request.Length > 1)
                    {
                        calibrationGpioMode = (byte)(request[1] & GpioModeMask);
                        RecalculateCalibrationOutput();
                    }
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
            RecalculateCalibrationOutput();
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
            var lastTraceIndex = frequencyTrace.Count < MaximumFrequencyTracePoints
                ? frequencyTrace.Count - 1
                : (frequencyTraceNext + MaximumFrequencyTracePoints - 1)
                    % MaximumFrequencyTracePoints;
            if(frequencyTrace.Count == 0
                || Math.Abs(frequencyTrace[lastTraceIndex].LocalOscillatorHz
                    - LocalOscillatorFrequencyHz) > 1.0
                || Math.Abs(frequencyTrace[lastTraceIndex].TunedInputHz
                    - TunedInputFrequencyHz) > 1.0)
            {
                var point = new FrequencyTracePoint(RssiSampleCount,
                    LocalOscillatorFrequencyHz, ReceiverFrequencyHz,
                    TunedInputFrequencyHz);
                if(frequencyTrace.Count < MaximumFrequencyTracePoints)
                {
                    frequencyTrace.Add(point);
                    frequencyTraceNext = frequencyTrace.Count
                        % MaximumFrequencyTracePoints;
                }
                else
                {
                    frequencyTrace[frequencyTraceNext] = point;
                    frequencyTraceNext = (frequencyTraceNext + 1)
                        % MaximumFrequencyTracePoints;
                    frequencyTraceWrapped = true;
                }
            }
            MinimumTunedInputFrequencyHz = Math.Min(MinimumTunedInputFrequencyHz, TunedInputFrequencyHz);
            MaximumTunedInputFrequencyHz = Math.Max(MaximumTunedInputFrequencyHz, TunedInputFrequencyHz);
            MinimumLocalOscillatorFrequencyHz = Math.Min(MinimumLocalOscillatorFrequencyHz, LocalOscillatorFrequencyHz);
            MaximumLocalOscillatorFrequencyHz = Math.Max(MaximumLocalOscillatorFrequencyHz, LocalOscillatorFrequencyHz);
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
            var selfTestFixtureActive = SelfTestFixture >= 3
                && SelfTestFixture != 5;
            if(CalibrationLoopbackConnected
                && (CalibrationOutputEnabled || selfTestFixtureActive))
            {
                level = Math.Max(level, SampleCalibrationLoopback());
            }
            return RecordRssi(DbmToRaw(level));
        }

        public string GetFrequencyTrace()
        {
            var builder = new StringBuilder();
            builder.Append($"ZS407_TWIN_RF_TRACE points={frequencyTrace.Count}");
            if(frequencyTrace.Count == 0)
            {
                return builder.ToString();
            }
            for(var slot = 0; slot < FrequencyTraceReportPoints; slot++)
            {
                var index = slot * (frequencyTrace.Count - 1)
                    / (FrequencyTraceReportPoints - 1);
                var physicalIndex = (frequencyTraceWrapped
                    ? frequencyTraceNext + index : index) % frequencyTrace.Count;
                var point = frequencyTrace[physicalIndex];
                builder.Append($" [{point.Sample}:{point.LocalOscillatorHz:F0},"
                    + $"{point.ReceiverHz:F0},{point.TunedInputHz:F0}]");
            }
            return builder.ToString();
        }

        private double SampleCalibrationLoopback()
        {
            // Tests 7/8 sweep the board's SAW/BPF tracking fixture rather
            // than observing the crystal line directly. The bridge selects
            // physical routing only; firmware still acquires and validates
            // every point and owns the result.
            double level;
            if(SelfTestFixture == 7 || SelfTestFixture == 8)
            {
                // Tracking mode holds the analyzer input at the 30 MHz
                // reference while sweeping the receiver IF across the board's
                // filter. A normal analyzer sweep only crosses 30 MHz once;
                // two adjacent samples near 30 MHz therefore identify the
                // start and direction of the real tracking acquisition.
                if(Math.Abs(TunedInputFrequencyHz - ReferenceFrequencyHz)
                    <= CalibrationTrackingInputToleranceHz)
                {
                    if(!trackingIfCandidateHz.HasValue)
                    {
                        trackingIfCandidateHz = ReceiverFrequencyHz;
                    }
                    else if(!trackingIfCenterHz.HasValue)
                    {
                        var delta = ReceiverFrequencyHz
                            - trackingIfCandidateHz.Value;
                        if(Math.Abs(delta) >= CalibrationTrackingMinimumStepHz
                            && Math.Abs(delta)
                                <= CalibrationTrackingMaximumStepHz)
                        {
                            trackingIfCenterHz = trackingIfCandidateHz.Value
                                + Math.Sign(delta)
                                    * CalibrationTrackingSpanHz / 2.0;
                        }
                        else if(Math.Abs(delta)
                            > CalibrationTrackingMaximumStepHz)
                        {
                            trackingIfCandidateHz = ReceiverFrequencyHz;
                        }
                    }
                }
                else if(!trackingIfCenterHz.HasValue)
                {
                    trackingIfCandidateHz = null;
                }

                level = trackingIfCenterHz.HasValue
                    ? SpectralLineLevelAt(ReceiverFrequencyHz,
                        trackingIfCenterHz.Value, CalibrationPowerDbm,
                        CalibrationBpfWidthHz)
                    : NoiseFloorDbm;
            }
            else
            {
                var lineWidth = SelfTestFixture == 13
                    ? CalibrationAttenuatorFixtureWidthHz
                    : SelfTestFixture == 14
                        ? CalibrationLnaFixtureWidthHz
                    : SelfTestFixture == 11
                        ? CalibrationSwitchFixtureWidthHz
                        : CalibrationLineWidthHz;
                level = SpectralLineLevelAt(SelfTestSampleFrequencyHz,
                    SelfTestCalibrationFrequencyHz,
                    SelfTestCalibrationPowerDbm,
                    lineWidth);
            }

            // The ZS407 self-test deliberately observes clock harmonics through
            // its direct path. Keep this deterministic and bounded to the range
            // actually exercised by the firmware.
            var calibrationFrequency = SelfTestCalibrationFrequencyHz;
            if(Math.Abs(calibrationFrequency - ReferenceFrequencyHz) < 1.0)
            {
                var harmonic = (int)Math.Round(SelfTestSampleFrequencyHz
                    / calibrationFrequency);
                if(harmonic >= 2 && harmonic <= MaximumCalibrationHarmonic)
                {
                    var harmonicPower = SelfTestCalibrationPowerDbm
                        - 20.0 * Math.Log10(harmonic);
                    level = Math.Max(level, SpectralLineLevelAt(
                        SelfTestSampleFrequencyHz,
                        calibrationFrequency * harmonic, harmonicPower,
                        CalibrationHarmonicWidthHz));
                }
            }

            // With the 15 MHz reference selected, the physical self-test routes
            // that clock through the ZS407 LPF/LNA fixture. These two aliases
            // model the board-specific pass path; the adjacent rejection point
            // intentionally has no alias.
            if(Math.Abs(calibrationFrequency - ReferenceFrequencyHz / 2.0) < 1.0)
            {
                level = Math.Max(level, SpectralLineLevelAt(
                    SelfTestSampleFrequencyHz, 795000000.0,
                    SelfTestCalibrationPowerDbm, CalibrationAliasWidthHz));
                level = Math.Max(level, SpectralLineLevelAt(
                    SelfTestSampleFrequencyHz, 915000000.0,
                    SelfTestCalibrationPowerDbm, CalibrationAliasWidthHz));
            }
            // The PE4302 controls the generator/switch leg during the switch
            // isolation and attenuation checks; it is not an input pad in
            // those physical fixtures.
            var fixtureAttenuation = SelfTestFixture == 11
                ? 0.0 : FrontEndAttenuationDb;
            return level - fixtureAttenuation;
        }

        private double SelfTestCalibrationFrequencyHz
        {
            get
            {
                // The Stage-1 fixture selects either the full or divided CAL
                // clock. Keep that routed source present after firmware
                // reuses the GPIO during direct/LPF acquisition.
                if(SelfTestFixture == 9 || SelfTestFixture == 10)
                {
                    return ReferenceFrequencyHz / 2.0;
                }
                if(SelfTestFixture >= 3 && SelfTestFixture != 5)
                {
                    return ReferenceFrequencyHz;
                }
                return CalibrationFrequencyHz;
            }
        }

        private double SelfTestSampleFrequencyHz
        {
            get
            {
                // The direct and LPF/LNA fixtures bypass the first mixer, so
                // their RF input is the Si4468 receive frequency itself.
                if(SelfTestFixture == 6)
                {
                    return ReceiverFrequencyHz;
                }
                return TunedInputFrequencyHz;
            }
        }

        private double SelfTestCalibrationPowerDbm => SelfTestFixture == 14
            ? CalibrationPowerDbm + CalibrationLnaFixtureGainDb
            : SelfTestFixture == 11
                ? CalibrationPowerDbm + CalibrationSwitchFixtureGainDb
                : CalibrationPowerDbm;

        private double SpectralLineLevel(double frequencyHz, double powerDbm,
            double widthHz)
        {
            return SpectralLineLevelAt(TunedInputFrequencyHz, frequencyHz,
                powerDbm, widthHz);
        }

        private static double SpectralLineLevelAt(double sampledFrequencyHz,
            double frequencyHz, double powerDbm, double widthHz)
        {
            var delta = Math.Abs(sampledFrequencyHz - frequencyHz);
            var halfWidth = widthHz / 2.0;
            var rolloff = delta <= halfWidth
                ? 0.0
                // The divided crystal clock is a narrow deterministic line.
                // A steep skirt keeps the self-test's adjacent stopband from
                // looking like broadband RF energy while remaining continuous
                // at the modeled line-width boundary.
                : 80.0 * Math.Log10(delta / halfWidth);
            return powerDbm - rolloff;
        }

        private void RecalculateCalibrationOutput()
        {
            byte clockConfig = 0;
            CalibrationOutputEnabled = calibrationGpioMode == GpioModeDividedClock
                && TryGetProperty(GlobalPropertyGroup, GlobalClockProperty,
                    out clockConfig)
                && (clockConfig & DividedClockEnable) != 0;
            if(!CalibrationOutputEnabled)
            {
                CalibrationFrequencyHz = 0;
                return;
            }
            var selection = (clockConfig >> DividedClockSelectionShift) & 0x7;
            CalibrationFrequencyHz = ReferenceFrequencyHz
                / dividedClockDivisors[selection];
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

        private sealed class FrequencyTracePoint
        {
            public FrequencyTracePoint(ulong sample, double localOscillatorHz,
                double receiverHz, double tunedInputHz)
            {
                Sample = sample;
                LocalOscillatorHz = localOscillatorHz;
                ReceiverHz = receiverHz;
                TunedInputHz = tunedInputHz;
            }

            public ulong Sample { get; }
            public double LocalOscillatorHz { get; }
            public double ReceiverHz { get; }
            public double TunedInputHz { get; }
        }

        private readonly List<byte> transaction = new List<byte>();
        private readonly Dictionary<ushort, byte> properties = new Dictionary<ushort, byte>();
        private readonly List<Tone> tones = new List<Tone>();
        private readonly List<FrequencyTracePoint> frequencyTrace =
            new List<FrequencyTracePoint>();
        private byte[] pendingResponse;
        private byte state;
        private byte channel;
        private byte? fixedRssi;
        private bool shutdown;
        private int frequencyTraceNext;
        private bool frequencyTraceWrapped;
        private double? trackingIfCandidateHz;
        private double? trackingIfCenterHz;

        private byte calibrationGpioMode;

        private const double ReferenceFrequencyHz = 30000000.0;
        private const double DefaultCalibrationPowerDbm = -35.3;
        private const double CalibrationLineWidthHz = 20000.0;
        private const double CalibrationHarmonicWidthHz = 200000.0;
        private const double CalibrationAliasWidthHz = 100000.0;
        private const double CalibrationSwitchFixtureWidthHz = 200000.0;
        private const double CalibrationSwitchFixtureGainDb = -12.0;
        private const double CalibrationAttenuatorFixtureWidthHz = 1000000.0;
        private const double CalibrationLnaFixtureWidthHz = 200000.0;
        private const double CalibrationLnaFixtureGainDb = 30.0;
        private const double CalibrationBpfWidthHz = 2000000.0;
        private const double CalibrationTrackingSpanHz = 14000000.0;
        private const double CalibrationTrackingInputToleranceHz = 100000.0;
        private const double CalibrationTrackingMinimumStepHz = 1000.0;
        private const double CalibrationTrackingMaximumStepHz = 500000.0;
        private const int MaximumCalibrationHarmonic = 40;
        private const int MaximumFrequencyTracePoints = 2048;
        private const int FrequencyTraceReportPoints = 17;
        private static readonly double[] dividedClockDivisors =
            { 1.0, 2.0, 3.0, 7.5, 10.0, 15.0, 30.0, 30.0 };
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
        private const byte GpioModeMask = 0x1F;
        private const byte GpioModeDividedClock = 0x07;
        private const byte GlobalPropertyGroup = 0x00;
        private const byte GlobalClockProperty = 0x01;
        private const byte DividedClockEnable = 0x40;
        private const int DividedClockSelectionShift = 3;
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
