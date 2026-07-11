// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Reflection;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.IRQControllers;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Compatibility shim for Renode 1.16.1, whose NVIC labels ICSR.RETTOBASE
    /// but returns zero unconditionally. ChibiOS/RT's Cortex-M7M port uses the
    /// architectural bit to decide whether an IRQ epilogue may reschedule.
    ///
    /// Remove this model when the pinned Renode release implements RETTOBASE.
    /// </summary>
    public sealed class NvicRetToBaseFix : IDoubleWordPeripheral, IKnownSize
    {
        public NvicRetToBaseFix(IMachine machine, NVIC nvic)
        {
            this.machine = machine;
            this.nvic = nvic;
            var field = typeof(NVIC).GetField("activeIRQs",
                BindingFlags.Instance | BindingFlags.NonPublic);
            if(field == null)
            {
                throw new InvalidOperationException("Renode NVIC activeIRQs field was not found");
            }
            activeInterrupts = (Stack<int>)field.GetValue(nvic);
        }

        public void Install()
        {
            if(installed)
            {
                return;
            }
            var sysbus = machine.GetSystemBus(nvic);
            sysbus.SetHookAfterPeripheralRead<uint>(nvic, FixRead);
            installed = true;
        }

        public void Reset()
        {
        }

        public long Size => 4;

        public uint ReadDoubleWord(long offset)
        {
            return installed ? 1u : 0u;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        private uint FixRead(uint value, long offset)
        {
            if(offset != InterruptControlState)
            {
                return value;
            }

            if(activeInterrupts.Count <= 1)
            {
                return value | ReturnToBase;
            }
            return value & ~ReturnToBase;
        }

        private readonly Stack<int> activeInterrupts;
        private readonly IMachine machine;
        private readonly NVIC nvic;
        private bool installed;
        private const long InterruptControlState = 0xD04;
        private const uint ReturnToBase = 1u << 11;
    }
}
