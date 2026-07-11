// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// ZS407 shared SPI wiring. Registration addresses and GPIO input numbers:
    /// 0 LCD, 1 microSD, 2 Si4468, 3 PE4302 LE, 4 MAX2871 LE.
    /// All select/latch signals are active low while bytes are shifted.
    /// Output-only RF parts may legitimately overlap another select, so this
    /// fabric broadcasts MOSI rather than rejecting multiple active devices.
    /// </summary>
    public sealed class ZS407SpiFabric : SimpleContainer<ISPIPeripheral>,
        ISPIPeripheral, IGPIOReceiver
    {
        public ZS407SpiFabric(IMachine machine) : base(machine)
        {
            lineStates = new Dictionary<int, bool>();
            Reset();
        }

        public ulong BusTransfers { get; private set; }

        public uint ActiveMask
        {
            get
            {
                var result = 0u;
                for(var address = FirstAddress; address <= LastAddress; ++address)
                {
                    if(IsSelected(address))
                    {
                        result |= 1u << address;
                    }
                }
                return result;
            }
        }

        public override void Reset()
        {
            lineStates.Clear();
            for(var address = FirstAddress; address <= LastAddress; ++address)
            {
                lineStates[address] = true;
            }
            BusTransfers = 0;
        }

        public void OnGPIO(int number, bool value)
        {
            ValidateAddress(number);
            var wasSelected = IsSelected(number);
            lineStates[number] = value;
            var isSelected = IsSelected(number);
            if(wasSelected && !isSelected && TryGetByAddress(number, out var peripheral))
            {
                peripheral.FinishTransmission();
            }
        }

        public byte Transmit(byte data)
        {
            BusTransfers++;
            UpdateRfFrontEndState();
            var response = (byte)0xFF;
            var hasReadableDevice = false;

            for(var address = FirstAddress; address <= LastAddress; ++address)
            {
                if(!IsSelected(address) || !TryGetByAddress(address, out var peripheral))
                {
                    continue;
                }
                var deviceResponse = peripheral.Transmit(data);
                if(address <= ReceiverAddress)
                {
                    response = hasReadableDevice ? (byte)(response & deviceResponse) : deviceResponse;
                    hasReadableDevice = true;
                }
            }
            return hasReadableDevice ? response : (byte)0;
        }

        public void FinishTransmission()
        {
            // Real transaction boundaries are the GPIO select/latch edges.
        }

        private void UpdateRfFrontEndState()
        {
            if(!TryGetByAddress(ReceiverAddress, out var receiver))
            {
                return;
            }

            var loFrequency = 0.0;
            if(TryGetByAddress(SynthesizerAddress, out var synthesizer))
            {
                loFrequency = ReadDoubleProperty(synthesizer, "FrequencyHz");
            }
            var attenuation = 0.0;
            if(TryGetByAddress(AttenuatorAddress, out var attenuator))
            {
                attenuation = ReadDoubleProperty(attenuator, "AttenuationDb");
            }
            var receiverFrequency = ReadDoubleProperty(receiver, "ReceiverFrequencyHz");
            var method = receiver.GetType().GetMethod("SetFrontEndState");
            method?.Invoke(receiver, new object[] {
                Math.Abs(loFrequency - receiverFrequency), attenuation
            });
        }

        private static double ReadDoubleProperty(object target, string name)
        {
            var property = target.GetType().GetProperty(name);
            return property == null ? 0.0 : Convert.ToDouble(property.GetValue(target));
        }

        private bool IsSelected(int address)
        {
            return lineStates.TryGetValue(address, out var high) && !high;
        }

        private static void ValidateAddress(int address)
        {
            if(address < FirstAddress || address > LastAddress)
            {
                throw new ArgumentOutOfRangeException(nameof(address));
            }
        }

        private readonly Dictionary<int, bool> lineStates;
        private const int FirstAddress = 0;
        private const int ReceiverAddress = 2;
        private const int AttenuatorAddress = 3;
        private const int SynthesizerAddress = 4;
        private const int LastAddress = 4;
    }
}
