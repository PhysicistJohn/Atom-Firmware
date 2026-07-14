// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Linq;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// STM32F303 channel DMA used by the display and ADC paths.
    /// Transfers are completed deterministically at the request boundary.
    /// </summary>
    public sealed class STM32F303Dma : IDoubleWordPeripheral, IKnownSize,
        INumberedGPIOOutput
    {
        public STM32F303Dma(IMachine machine, int numberOfChannels)
        {
            if(numberOfChannels < 1 || numberOfChannels > 7)
            {
                throw new ArgumentOutOfRangeException(nameof(numberOfChannels));
            }

            sysbus = machine.GetSystemBus(this);
            channels = Enumerable.Range(0, numberOfChannels)
                .Select(_ => new Channel()).ToArray();
            Connections = Enumerable.Range(0, numberOfChannels)
                .ToDictionary(i => i, _ => (IGPIO)new GPIO());
        }

        public long Size => 0x400;

        public IReadOnlyDictionary<int, IGPIO> Connections { get; }

        public void Reset()
        {
            interruptStatus = 0;
            channelSelection = 0;
            foreach(var channel in channels)
            {
                channel.Control = 0;
                channel.Remaining = 0;
                channel.PeripheralAddress = 0;
                channel.MemoryAddress = 0;
                channel.InitialCount = 0;
            }
            UpdateInterrupts();
        }

        public uint ReadDoubleWord(long offset)
        {
            if(offset == InterruptStatus)
            {
                return interruptStatus;
            }
            if(offset == InterruptFlagClear)
            {
                return 0;
            }
            if(offset == ChannelSelection)
            {
                return channelSelection;
            }
            return DecodeChannel(offset, out var channel, out var register)
                ? ReadChannel(channel, register)
                : 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == InterruptFlagClear)
            {
                interruptStatus &= ~value;
                UpdateInterrupts();
                return;
            }
            if(offset == ChannelSelection)
            {
                channelSelection = value;
                return;
            }
            if(!DecodeChannel(offset, out var channelIndex, out var register))
            {
                return;
            }

            var channel = channels[channelIndex];
            switch(register)
            {
                case ChannelControl:
                    channel.Control = value;
                    if((value & Enable) != 0 &&
                        ((value & DirectionMemoryToPeripheral) != 0 ||
                         (value & MemoryToMemory) != 0))
                    {
                        CompleteTransfer(channelIndex, null);
                    }
                    break;
                case ChannelCount:
                    channel.Remaining = value & 0xFFFFu;
                    channel.InitialCount = channel.Remaining;
                    break;
                case ChannelPeripheralAddress:
                    channel.PeripheralAddress = value;
                    break;
                case ChannelMemoryAddress:
                    channel.MemoryAddress = value;
                    break;
            }
        }

        public uint GetTransferCount(int channel)
        {
            ValidateChannel(channel);
            return channels[channel].Remaining;
        }

        public bool IsEnabled(int channel)
        {
            ValidateChannel(channel);
            return (channels[channel].Control & Enable) != 0;
        }

        public void CompletePeripheralToMemory(int channel, Func<uint> provider)
        {
            ValidateChannel(channel);
            if(provider == null)
            {
                throw new ArgumentNullException(nameof(provider));
            }
            CompleteTransfer(channel, provider);
        }

        private void CompleteTransfer(int channelIndex, Func<uint> peripheralProvider)
        {
            var channel = channels[channelIndex];
            if((channel.Control & Enable) == 0 || channel.Remaining == 0)
            {
                return;
            }

            var memoryWidth = DecodeWidth(channel.Control, MemorySizeShift);
            var peripheralWidth = DecodeWidth(channel.Control, PeripheralSizeShift);
            var count = channel.Remaining;
            var memoryAddress = (ulong)channel.MemoryAddress;
            var peripheralAddress = (ulong)channel.PeripheralAddress;
            var memoryToPeripheral = (channel.Control & DirectionMemoryToPeripheral) != 0;
            var memoryToMemory = (channel.Control & MemoryToMemory) != 0;

            for(var i = 0u; i < count; ++i)
            {
                if(memoryToPeripheral || memoryToMemory)
                {
                    var value = Read(memoryAddress, memoryWidth);
                    Write(peripheralAddress, value, peripheralWidth);
                    if(!memoryToMemory)
                    {
                        ServicePendingPeripheralToMemory(peripheralAddress);
                    }
                }
                else
                {
                    var value = peripheralProvider != null
                        ? peripheralProvider()
                        : Read(peripheralAddress, peripheralWidth);
                    Write(memoryAddress, value, memoryWidth);
                }

                if((channel.Control & MemoryIncrement) != 0)
                {
                    memoryAddress += (ulong)memoryWidth;
                }
                if((channel.Control & PeripheralIncrement) != 0)
                {
                    peripheralAddress += (ulong)peripheralWidth;
                }
            }

            channel.Remaining = 0;
            SetFlags(channelIndex, GlobalFlag | TransferCompleteFlag);

            if((channel.Control & CircularMode) != 0)
            {
                channel.Remaining = channel.InitialCount;
            }
            else
            {
                channel.Control &= ~Enable;
            }
            UpdateInterrupts();
        }

        private void ServicePendingPeripheralToMemory(ulong requestAddress)
        {
            for(var channelIndex = 0; channelIndex < channels.Length;
                ++channelIndex)
            {
                var channel = channels[channelIndex];
                if((channel.Control & Enable) == 0 || channel.Remaining == 0
                    || (channel.Control & DirectionMemoryToPeripheral) != 0
                    || (channel.Control & MemoryToMemory) != 0
                    || channel.PeripheralAddress != requestAddress)
                {
                    continue;
                }

                var memoryWidth = DecodeWidth(channel.Control, MemorySizeShift);
                var peripheralWidth = DecodeWidth(channel.Control,
                    PeripheralSizeShift);
                var completed = channel.InitialCount - channel.Remaining;
                var memoryAddress = (ulong)channel.MemoryAddress;
                var peripheralAddress = (ulong)channel.PeripheralAddress;
                if((channel.Control & MemoryIncrement) != 0)
                {
                    memoryAddress += completed * (ulong)memoryWidth;
                }
                if((channel.Control & PeripheralIncrement) != 0)
                {
                    peripheralAddress += completed * (ulong)peripheralWidth;
                }

                Write(memoryAddress, Read(peripheralAddress, peripheralWidth),
                    memoryWidth);
                channel.Remaining--;
                if(channel.Remaining != 0)
                {
                    continue;
                }

                SetFlags(channelIndex, GlobalFlag | TransferCompleteFlag);
                if((channel.Control & CircularMode) != 0)
                {
                    channel.Remaining = channel.InitialCount;
                }
                else
                {
                    channel.Control &= ~Enable;
                }
                UpdateInterrupts();
            }
        }

        private uint ReadChannel(int channelIndex, long register)
        {
            var channel = channels[channelIndex];
            return register switch
            {
                ChannelControl => channel.Control,
                ChannelCount => channel.Remaining,
                ChannelPeripheralAddress => channel.PeripheralAddress,
                ChannelMemoryAddress => channel.MemoryAddress,
                _ => 0,
            };
        }

        private bool DecodeChannel(long offset, out int channel, out long register)
        {
            channel = -1;
            register = -1;
            if(offset < FirstChannel || offset >= FirstChannel + channels.Length * ChannelStride)
            {
                return false;
            }
            var relative = offset - FirstChannel;
            channel = (int)(relative / ChannelStride);
            register = relative % ChannelStride;
            return register <= ChannelMemoryAddress;
        }

        private void SetFlags(int channel, uint flags)
        {
            interruptStatus |= flags << (channel * 4);
        }

        private void UpdateInterrupts()
        {
            for(var i = 0; i < channels.Length; ++i)
            {
                var flags = (interruptStatus >> (i * 4)) & 0xFu;
                var control = channels[i].Control;
                var active = ((flags & TransferCompleteFlag) != 0 &&
                              (control & TransferCompleteInterruptEnable) != 0) ||
                             ((flags & HalfTransferFlag) != 0 &&
                              (control & HalfTransferInterruptEnable) != 0) ||
                             ((flags & TransferErrorFlag) != 0 &&
                              (control & TransferErrorInterruptEnable) != 0);
                Connections[i].Set(active);
            }
        }

        private uint Read(ulong address, int width)
        {
            return width switch
            {
                1 => sysbus.ReadByte(address, this),
                2 => sysbus.ReadWord(address, this),
                _ => sysbus.ReadDoubleWord(address, this),
            };
        }

        private void Write(ulong address, uint value, int width)
        {
            switch(width)
            {
                case 1:
                    sysbus.WriteByte(address, (byte)value, this);
                    break;
                case 2:
                    sysbus.WriteWord(address, (ushort)value, this);
                    break;
                default:
                    sysbus.WriteDoubleWord(address, value, this);
                    break;
            }
        }

        private static int DecodeWidth(uint control, int shift)
        {
            return ((control >> shift) & 0x3u) switch
            {
                0 => 1,
                1 => 2,
                2 => 4,
                _ => 4,
            };
        }

        private void ValidateChannel(int channel)
        {
            if(channel < 0 || channel >= channels.Length)
            {
                throw new ArgumentOutOfRangeException(nameof(channel));
            }
        }

        private sealed class Channel
        {
            public uint Control;
            public uint Remaining;
            public uint PeripheralAddress;
            public uint MemoryAddress;
            public uint InitialCount;
        }

        private readonly IBusController sysbus;
        private readonly Channel[] channels;
        private uint interruptStatus;
        private uint channelSelection;

        private const uint Enable = 1u << 0;
        private const uint TransferCompleteInterruptEnable = 1u << 1;
        private const uint HalfTransferInterruptEnable = 1u << 2;
        private const uint TransferErrorInterruptEnable = 1u << 3;
        private const uint DirectionMemoryToPeripheral = 1u << 4;
        private const uint CircularMode = 1u << 5;
        private const uint PeripheralIncrement = 1u << 6;
        private const uint MemoryIncrement = 1u << 7;
        private const uint MemoryToMemory = 1u << 14;
        private const int PeripheralSizeShift = 8;
        private const int MemorySizeShift = 10;

        private const uint GlobalFlag = 1u << 0;
        private const uint TransferCompleteFlag = 1u << 1;
        private const uint HalfTransferFlag = 1u << 2;
        private const uint TransferErrorFlag = 1u << 3;

        private const long InterruptStatus = 0x00;
        private const long InterruptFlagClear = 0x04;
        private const long FirstChannel = 0x08;
        private const long ChannelStride = 0x14;
        private const long ChannelControl = 0x00;
        private const long ChannelCount = 0x04;
        private const long ChannelPeripheralAddress = 0x08;
        private const long ChannelMemoryAddress = 0x0C;
        private const long ChannelSelection = 0xA8;
    }
}
