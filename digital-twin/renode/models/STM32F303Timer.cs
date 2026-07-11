// SPDX-License-Identifier: MIT

using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// STM32F303 timer subset with hardware-faithful UIF behavior.
    ///
    /// Renode 1.16.1's generic STM32 timer only raises UIF when UIE is set.
    /// Real STM32 timers set UIF independently of interrupt enable; ChibiOS
    /// relies on that behavior for gptPolledDelay().
    /// </summary>
    public sealed class STM32F303Timer : LimitTimer, IDoubleWordPeripheral, IKnownSize
    {
        public STM32F303Timer(IMachine machine, ulong frequency, uint initialLimit)
            : base(machine.ClockSource, frequency, limit: initialLimit,
                direction: Direction.Ascending, enabled: false,
                eventEnabled: true, autoUpdate: false)
        {
            sysbus = machine.GetSystemBus(this);
            this.initialLimit = initialLimit;

            LimitReached += () =>
            {
                if((control1 & UpdateDisable) != 0)
                {
                    return;
                }

                status |= UpdateInterruptFlag;
                if((control1 & OnePulseMode) != 0)
                {
                    control1 &= ~CounterEnable;
                    Enabled = false;
                }
                else
                {
                    Limit = autoReload;
                }
                UpdateInterrupt();
            };

            Reset();
        }

        public long Size => 0x400;

        [DefaultInterrupt]
        public GPIO IRQ { get; } = new GPIO();

        public override void Reset()
        {
            base.Reset();
            registers.Clear();
            control1 = 0;
            interruptEnable = 0;
            status = 0;
            autoReload = initialLimit;
            Divider = 1;
            Limit = initialLimit;
            Value = 0;
            Enabled = false;
            Mode = WorkMode.Periodic;
            IRQ.Unset();
        }

        public uint ReadDoubleWord(long offset)
        {
            SyncCpuTime();
            return offset switch
            {
                Control1 => control1,
                InterruptEnable => interruptEnable,
                Status => status,
                Counter => (uint)Value,
                Prescaler => (uint)(Divider - 1),
                AutoReload => autoReload,
                _ => registers.TryGetValue(offset, out var value) ? value : 0,
            };
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            SyncCpuTime();
            switch(offset)
            {
                case Control1:
                    control1 = value;
                    Mode = (value & OnePulseMode) != 0
                        ? WorkMode.OneShot
                        : WorkMode.Periodic;
                    this.Direction = (value & DirectionDown) != 0
                        ? Direction.Descending
                        : Direction.Ascending;
                    Enabled = (value & CounterEnable) != 0 && autoReload > 0;
                    break;
                case InterruptEnable:
                    interruptEnable = value;
                    UpdateInterrupt();
                    break;
                case Status:
                    // STM32 status flags are cleared by writing zero.
                    status &= value;
                    UpdateInterrupt();
                    break;
                case EventGeneration:
                    if((value & UpdateGeneration) != 0 &&
                        (control1 & UpdateDisable) == 0)
                    {
                        Value = this.Direction == Direction.Ascending ? 0 : autoReload;
                        Limit = autoReload;
                        if((control1 & UpdateRequestSource) == 0)
                        {
                            status |= UpdateInterruptFlag;
                            UpdateInterrupt();
                        }
                    }
                    break;
                case Counter:
                    Value = value;
                    break;
                case Prescaler:
                    Divider = (value & 0xFFFFu) + 1u;
                    break;
                case AutoReload:
                    autoReload = value;
                    Limit = value;
                    Enabled = (control1 & CounterEnable) != 0 && autoReload > 0;
                    break;
                default:
                    registers[offset] = value;
                    break;
            }
        }

        private void SyncCpuTime()
        {
            if(sysbus.TryGetCurrentCPU(out var cpu))
            {
                cpu.SyncTime();
            }
        }

        private void UpdateInterrupt()
        {
            IRQ.Set((interruptEnable & UpdateInterruptEnable) != 0 &&
                (status & UpdateInterruptFlag) != 0);
        }

        private readonly IBusController sysbus;
        private readonly uint initialLimit;
        private readonly Dictionary<long, uint> registers = new Dictionary<long, uint>();

        private uint control1;
        private uint interruptEnable;
        private uint status;
        private uint autoReload;

        private const uint CounterEnable = 1u << 0;
        private const uint UpdateDisable = 1u << 1;
        private const uint UpdateRequestSource = 1u << 2;
        private const uint OnePulseMode = 1u << 3;
        private const uint DirectionDown = 1u << 4;
        private const uint UpdateInterruptEnable = 1u << 0;
        private const uint UpdateInterruptFlag = 1u << 0;
        private const uint UpdateGeneration = 1u << 0;

        private const long Control1 = 0x00;
        private const long InterruptEnable = 0x0C;
        private const long Status = 0x10;
        private const long EventGeneration = 0x14;
        private const long Counter = 0x24;
        private const long Prescaler = 0x28;
        private const long AutoReload = 0x2C;
    }
}
