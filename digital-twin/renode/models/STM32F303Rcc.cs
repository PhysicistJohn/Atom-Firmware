// SPDX-License-Identifier: MIT

using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Behavioral subset of the STM32F303 reset and clock controller.
    ///
    /// Oscillators become ready immediately in virtual time and the clock
    /// switch status follows the selected source. All remaining implemented
    /// registers retain their written value. This is sufficient to execute
    /// the real ChibiOS clock startup without patching firmware code.
    /// </summary>
    public sealed class STM32F303Rcc : IDoubleWordPeripheral, IKnownSize
    {
        public STM32F303Rcc()
        {
            Reset();
        }

        public long Size => 0x400;

        public void Reset()
        {
            registers.Clear();
            // HSION, HSIRDY and the reset HSITRIM value.
            registers[ClockControl] = 0x00000083;
            registers[ClockConfiguration] = 0x00000000;
            registers[ControlStatus] = 0x00000000;
            registers[BackupDomainControl] = 0x00000000;
        }

        public uint ReadDoubleWord(long offset)
        {
            registers.TryGetValue(offset, out var value);
            return offset switch
            {
                ClockControl => MirrorReadyBits(value),
                ClockConfiguration => MirrorClockSwitchStatus(value),
                ControlStatus => MirrorEnableToReady(value, 0, 1),
                BackupDomainControl => MirrorEnableToReady(value, 0, 1),
                _ => value,
            };
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case ClockControl:
                    registers[offset] = MirrorReadyBits(value);
                    break;
                case ClockConfiguration:
                    registers[offset] = MirrorClockSwitchStatus(value);
                    break;
                case ControlStatus:
                    // RM0316: RMVF clears reset flags rather than latching.
                    if((value & (1u << 24)) != 0)
                    {
                        value &= 0x01FFFFFFu;
                    }
                    registers[offset] = MirrorEnableToReady(value, 0, 1);
                    break;
                case BackupDomainControl:
                    registers[offset] = MirrorEnableToReady(value, 0, 1);
                    break;
                case ClockInterrupt:
                    // Ready flags are synthesized; interrupt clear bits do
                    // not remain set in the register image.
                    registers[offset] = value & 0x0000FF00u;
                    break;
                default:
                    registers[offset] = value;
                    break;
            }
        }

        private static uint MirrorReadyBits(uint value)
        {
            value = MirrorEnableToReady(value, 0, 1);      // HSI
            value = MirrorEnableToReady(value, 16, 17);    // HSE
            value = MirrorEnableToReady(value, 24, 25);    // PLL
            return value;
        }

        private static uint MirrorClockSwitchStatus(uint value)
        {
            return (value & ~(3u << 2)) | ((value & 3u) << 2);
        }

        private static uint MirrorEnableToReady(uint value, int enableBit, int readyBit)
        {
            var readyMask = 1u << readyBit;
            return (value & (1u << enableBit)) != 0
                ? value | readyMask
                : value & ~readyMask;
        }

        private readonly Dictionary<long, uint> registers = new Dictionary<long, uint>();

        private const long ClockControl = 0x00;
        private const long ClockConfiguration = 0x04;
        private const long ClockInterrupt = 0x08;
        private const long BackupDomainControl = 0x20;
        private const long ControlStatus = 0x24;
    }
}
