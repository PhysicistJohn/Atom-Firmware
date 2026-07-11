// SPDX-License-Identifier: MIT

using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>PE4302-compatible 6-bit, 0.5 dB step attenuator.</summary>
    public sealed class PE4302 : ISPIPeripheral
    {
        public byte Code { get; private set; }

        public double AttenuationDb => (Code & 0x3F) * 0.5;

        public ulong LatchCount { get; private set; }

        public void Reset()
        {
            shifted = 0;
            Code = 0;
            LatchCount = 0;
        }

        public byte Transmit(byte data)
        {
            shifted = data;
            return 0;
        }

        public void FinishTransmission()
        {
            Code = (byte)(shifted & 0x3F);
            LatchCount++;
        }

        private byte shifted;
    }
}
