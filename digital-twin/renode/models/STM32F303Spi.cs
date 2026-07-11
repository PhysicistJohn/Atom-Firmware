// SPDX-License-Identifier: MIT

using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// STM32F303 SPI v2 controller model.
    ///
    /// The older generic Renode STM32 model only emits one byte for a 16-bit
    /// access to DR. The F303 supports data packing: with DS=8, a half-word
    /// access emits two byte frames, least-significant byte first. tinySA uses
    /// exactly that mode for RGB565 DMA, so access width is observable device
    /// behavior rather than an implementation detail.
    /// </summary>
    public sealed class STM32F303Spi :
        NullRegistrationPointPeripheralContainer<ISPIPeripheral>,
        IBytePeripheral, IWordPeripheral, IDoubleWordPeripheral, IKnownSize
    {
        public STM32F303Spi(IMachine machine) : base(machine)
        {
            IRQ = new GPIO();
            Reset();
        }

        public long Size => 0x400;

        public GPIO IRQ { get; }

        public override void Reset()
        {
            control1 = 0;
            control2 = 0;
            crcPolynomial = 7;
            received.Clear();
            otherRegisters.Clear();
            IRQ.Unset();
        }

        public byte ReadByte(long offset)
        {
            if(offset == Data)
            {
                return ReadResponse();
            }
            return (byte)ReadDoubleWord(offset);
        }

        public void WriteByte(long offset, byte value)
        {
            if(offset == Data)
            {
                Transfer(value);
                return;
            }
            WriteDoubleWord(offset, value);
        }

        public ushort ReadWord(long offset)
        {
            if(offset == Data)
            {
                var low = ReadResponse();
                var high = ReadResponse();
                return (ushort)(low | (high << 8));
            }
            return (ushort)ReadDoubleWord(offset);
        }

        public void WriteWord(long offset, ushort value)
        {
            if(offset == Data)
            {
                Transfer((byte)value);
                Transfer((byte)(value >> 8));
                return;
            }
            WriteDoubleWord(offset, value);
        }

        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case Control1:
                    return control1;
                case Control2:
                    return control2;
                case Status:
                    return TransmitEmpty | (received.Count != 0 ? ReceiveNotEmpty : 0u);
                case Data:
                    return ReadResponse();
                case CrcPolynomial:
                    return crcPolynomial;
                default:
                    return otherRegisters.TryGetValue(offset, out var value) ? value : 0;
            }
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case Control1:
                    control1 = value;
                    break;
                case Control2:
                    control2 = value;
                    UpdateInterrupt();
                    break;
                case Data:
                    Transfer((byte)value);
                    Transfer((byte)(value >> 8));
                    Transfer((byte)(value >> 16));
                    Transfer((byte)(value >> 24));
                    break;
                case CrcPolynomial:
                    crcPolynomial = value;
                    break;
                default:
                    otherRegisters[offset] = value;
                    break;
            }
        }

        private void Transfer(byte value)
        {
            var response = RegisteredPeripheral != null
                ? RegisteredPeripheral.Transmit(value)
                : (byte)0xFF;

            // The physical receive FIFO is four bytes deep. Old unread data is
            // overrun by display-only traffic; retaining an unbounded queue
            // would be both inaccurate and very expensive during redraws.
            if(received.Count == ReceiveFifoCapacity)
            {
                received.Dequeue();
            }
            received.Enqueue(response);
            UpdateInterrupt();
        }

        private byte ReadResponse()
        {
            var result = received.Count != 0 ? received.Dequeue() : (byte)0;
            UpdateInterrupt();
            return result;
        }

        private void UpdateInterrupt()
        {
            var receiveInterrupt = (control2 & ReceiveNotEmptyInterruptEnable) != 0
                && received.Count != 0;
            var transmitInterrupt = (control2 & TransmitEmptyInterruptEnable) != 0;
            IRQ.Set(receiveInterrupt || transmitInterrupt);
        }

        private readonly Queue<byte> received = new Queue<byte>();
        private readonly Dictionary<long, uint> otherRegisters = new Dictionary<long, uint>();
        private uint control1;
        private uint control2;
        private uint crcPolynomial;

        private const int ReceiveFifoCapacity = 4;
        private const uint ReceiveNotEmpty = 1u << 0;
        private const uint TransmitEmpty = 1u << 1;
        private const uint ReceiveNotEmptyInterruptEnable = 1u << 6;
        private const uint TransmitEmptyInterruptEnable = 1u << 7;

        private const long Control1 = 0x00;
        private const long Control2 = 0x04;
        private const long Status = 0x08;
        private const long Data = 0x0C;
        private const long CrcPolynomial = 0x10;
    }
}
