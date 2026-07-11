// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// MAX2871/ADF4351-compatible 32-bit synthesizer register sink.
    /// LE rising is represented by FinishTransmission from the shared bus.
    /// </summary>
    public sealed class MAX2871 : ISPIPeripheral
    {
        public double FrequencyHz { get; private set; }

        public bool OutputEnabled { get; private set; }

        public int OutputPowerCode { get; private set; }

        public ulong RegisterWrites { get; private set; }

        public void Reset()
        {
            shiftBytes.Clear();
            Array.Clear(registers, 0, registers.Length);
            FrequencyHz = 0;
            OutputEnabled = false;
            OutputPowerCode = 0;
            RegisterWrites = 0;
        }

        public byte Transmit(byte data)
        {
            if(shiftBytes.Count == 4)
            {
                shiftBytes.RemoveAt(0);
            }
            shiftBytes.Add(data);
            return 0;
        }

        public void FinishTransmission()
        {
            if(shiftBytes.Count != 4)
            {
                shiftBytes.Clear();
                return;
            }

            var value = ((uint)shiftBytes[0] << 24)
                | ((uint)shiftBytes[1] << 16)
                | ((uint)shiftBytes[2] << 8)
                | shiftBytes[3];
            shiftBytes.Clear();
            var address = (int)(value & 0x7u);
            if(address >= registers.Length)
            {
                return;
            }
            registers[address] = value;
            RegisterWrites++;
            RecalculateOutput();
        }

        public uint GetRegister(int address)
        {
            if(address < 0 || address >= registers.Length)
            {
                throw new ArgumentOutOfRangeException(nameof(address));
            }
            return registers[address];
        }

        private void RecalculateOutput()
        {
            var integer = (registers[0] >> 15) & 0xFFFFu;
            var fraction = (registers[0] >> 3) & 0xFFFu;
            var modulus = (registers[1] >> 3) & 0xFFFu;
            if(modulus == 0)
            {
                modulus = 1;
            }

            var referenceDivider = (registers[2] >> 14) & 0x3FFu;
            if(referenceDivider == 0)
            {
                referenceDivider = 1;
            }
            var referenceDoubler = (registers[2] & (1u << 25)) != 0 ? 2.0 : 1.0;
            var referenceDivideByTwo = (registers[2] & (1u << 24)) != 0 ? 2.0 : 1.0;
            var phaseFrequencyDetector = ReferenceFrequencyHz * referenceDoubler
                / (referenceDivider * referenceDivideByTwo);
            var vco = (integer + fraction / (double)modulus) * phaseFrequencyDetector;
            var outputDividerCode = (int)((registers[4] >> 20) & 0x7u);
            FrequencyHz = vco / (1 << outputDividerCode);
            OutputEnabled = (registers[4] & (1u << 5)) != 0
                && (registers[2] & (1u << 5)) == 0;
            OutputPowerCode = (int)((registers[4] >> 3) & 0x3u);
        }

        private readonly uint[] registers = new uint[6];
        private readonly List<byte> shiftBytes = new List<byte>();
        private const double ReferenceFrequencyHz = 30000000.0;
    }
}
