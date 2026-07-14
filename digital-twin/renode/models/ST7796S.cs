// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.IO;
using Antmicro.Renode.Backends.Display;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.Video;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// ST7796S-compatible 480x320 SPI display used by the ZS407.
    /// It implements the command/data protocol used by the firmware and is a
    /// normal Renode video source, so TakeScreenshot and video analyzers work.
    /// GPIO input 0 is D/C and input 1 is RESET (active low).
    /// </summary>
    public sealed class ST7796S : AutoRepaintingVideo, ISPIPeripheral, IGPIOReceiver
    {
        public ST7796S(IMachine machine) : base(machine)
        {
            Endianess = ELFSharp.ELF.Endianess.BigEndian;
            Reconfigure(ScreenWidth, ScreenHeight, PixelFormat.RGB565);
            Reset();
        }

        public ulong PixelWrites { get; private set; }

        public ulong CommandWrites { get; private set; }

        public ulong MemoryReadBytes { get; private set; }

        public bool DisplayEnabled { get; private set; }

        public byte MemoryAccessControl => memoryAccessControl;

        public uint NonBlackPixels
        {
            get
            {
                var count = 0u;
                for(var i = 0; i < buffer.Length; i += 2)
                {
                    if(buffer[i] != 0 || buffer[i + 1] != 0)
                    {
                        count++;
                    }
                }
                return count;
            }
        }

        public ulong FramebufferHash
        {
            get
            {
                // FNV-1a is used only as a deterministic framebuffer identity,
                // not as a security primitive.
                var hash = 14695981039346656037UL;
                for(var i = 0; i < buffer.Length; ++i)
                {
                    hash ^= buffer[i];
                    hash *= 1099511628211UL;
                }
                return hash;
            }
        }

        public override void Reset()
        {
            Array.Clear(buffer, 0, buffer.Length);
            parameters.Clear();
            currentCommand = 0;
            columnStart = 0;
            columnEnd = ScreenWidth - 1;
            pageStart = 0;
            pageEnd = ScreenHeight - 1;
            cursorX = 0;
            cursorY = 0;
            memoryAccessControl = 0x28;
            firstPixelBytePending = false;
            readSecondBytePending = false;
            readDummyPending = false;
            dataMode = true;
            resetAsserted = false;
            DisplayEnabled = false;
            PixelWrites = 0;
            CommandWrites = 0;
            MemoryReadBytes = 0;
        }

        public void OnGPIO(int number, bool value)
        {
            switch(number)
            {
                case DataCommandInput:
                    dataMode = value;
                    break;
                case ResetInput:
                    var assertReset = !value;
                    if(assertReset && !resetAsserted)
                    {
                        ResetControllerState();
                    }
                    resetAsserted = assertReset;
                    break;
                default:
                    throw new ArgumentOutOfRangeException(nameof(number));
            }
        }

        public byte Transmit(byte data)
        {
            if(resetAsserted)
            {
                return 0;
            }

            if(!dataMode)
            {
                BeginCommand(data);
            }
            else if(currentCommand == MemoryRead
                || currentCommand == MemoryReadContinue)
            {
                return ReadMemoryByte();
            }
            else
            {
                AcceptData(data);
            }
            return 0;
        }

        public void FinishTransmission()
        {
            firstPixelBytePending = false;
            readSecondBytePending = false;
            readDummyPending = false;
        }

        public ushort GetPixel(int x, int y)
        {
            if(x < 0 || x >= ScreenWidth || y < 0 || y >= ScreenHeight)
            {
                throw new ArgumentOutOfRangeException();
            }
            var offset = (y * ScreenWidth + x) * 2;
            return (ushort)((buffer[offset] << 8) | buffer[offset + 1]);
        }

        public void SaveScreenshot(string path)
        {
            using(var png = TakeScreenshot().ToPng())
            using(var output = File.Create(path))
            {
                png.CopyTo(output);
            }
        }

        public void SaveRgb565LittleEndian(string path)
        {
            using(var output = File.Create(path))
            {
                for(var offset = 0; offset < buffer.Length; offset += 2)
                {
                    // The ST7796S wire order is big-endian RGB565; tinySA's
                    // host capture contract is explicitly little-endian.
                    output.WriteByte(buffer[offset + 1]);
                    output.WriteByte(buffer[offset]);
                }
            }
        }

        protected override void Repaint()
        {
            // SPI writes already update the retained panel GRAM in `buffer`.
        }

        private void BeginCommand(byte command)
        {
            currentCommand = command;
            parameters.Clear();
            firstPixelBytePending = false;
            readSecondBytePending = false;
            readDummyPending = false;
            CommandWrites++;

            switch(command)
            {
                case SoftwareReset:
                    ResetControllerState();
                    break;
                case DisplayOff:
                    DisplayEnabled = false;
                    break;
                case DisplayOn:
                    DisplayEnabled = true;
                    break;
                case MemoryWrite:
                case MemoryWriteContinue:
                    cursorX = columnStart;
                    cursorY = pageStart;
                    break;
                case MemoryRead:
                case MemoryReadContinue:
                    cursorX = columnStart;
                    cursorY = pageStart;
                    readDummyPending = true;
                    break;
            }
        }

        private void AcceptData(byte value)
        {
            switch(currentCommand)
            {
                case ColumnAddressSet:
                    AcceptAddressByte(value, true);
                    break;
                case PageAddressSet:
                    AcceptAddressByte(value, false);
                    break;
                case MemoryAccessControlCommand:
                    memoryAccessControl = value;
                    break;
                case MemoryWrite:
                case MemoryWriteContinue:
                    AcceptPixelByte(value);
                    break;
                default:
                    parameters.Add(value);
                    break;
            }
        }

        private void AcceptAddressByte(byte value, bool column)
        {
            parameters.Add(value);
            if(parameters.Count != 4)
            {
                return;
            }

            var start = (parameters[0] << 8) | parameters[1];
            var end = (parameters[2] << 8) | parameters[3];
            if(column)
            {
                columnStart = Clamp(start, 0, ScreenWidth - 1);
                columnEnd = Clamp(end, columnStart, ScreenWidth - 1);
            }
            else
            {
                pageStart = Clamp(start, 0, ScreenHeight - 1);
                pageEnd = Clamp(end, pageStart, ScreenHeight - 1);
            }
            parameters.Clear();
        }

        private void AcceptPixelByte(byte value)
        {
            if(!firstPixelBytePending)
            {
                firstPixelByte = value;
                firstPixelBytePending = true;
                return;
            }

            WritePixel(firstPixelByte, value);
            firstPixelBytePending = false;
            AdvanceCursor();
        }

        private void WritePixel(byte high, byte low)
        {
            var x = cursorX;
            var y = cursorY;
            if((memoryAccessControl & FlipBothAxes) == FlipBothAxes)
            {
                x = ScreenWidth - 1 - x;
                y = ScreenHeight - 1 - y;
            }

            if(x >= 0 && x < ScreenWidth && y >= 0 && y < ScreenHeight)
            {
                var offset = (y * ScreenWidth + x) * 2;
                buffer[offset] = high;
                buffer[offset + 1] = low;
                PixelWrites++;
            }
        }

        private byte ReadMemoryByte()
        {
            MemoryReadBytes++;
            if(readDummyPending)
            {
                readDummyPending = false;
                return 0;
            }

            var x = cursorX;
            var y = cursorY;
            if((memoryAccessControl & FlipBothAxes) == FlipBothAxes)
            {
                x = ScreenWidth - 1 - x;
                y = ScreenHeight - 1 - y;
            }
            var offset = (y * ScreenWidth + x) * 2;
            if(!readSecondBytePending)
            {
                readSecondBytePending = true;
                return buffer[offset];
            }

            readSecondBytePending = false;
            var result = buffer[offset + 1];
            AdvanceCursor();
            return result;
        }

        private void AdvanceCursor()
        {
            cursorX++;
            if(cursorX <= columnEnd)
            {
                return;
            }
            cursorX = columnStart;
            cursorY++;
            if(cursorY > pageEnd)
            {
                cursorY = pageStart;
            }
        }

        private void ResetControllerState()
        {
            Array.Clear(buffer, 0, buffer.Length);
            parameters.Clear();
            currentCommand = 0;
            columnStart = 0;
            columnEnd = ScreenWidth - 1;
            pageStart = 0;
            pageEnd = ScreenHeight - 1;
            cursorX = 0;
            cursorY = 0;
            memoryAccessControl = 0x28;
            firstPixelBytePending = false;
            readSecondBytePending = false;
            readDummyPending = false;
            DisplayEnabled = false;
        }

        private static int Clamp(int value, int minimum, int maximum)
        {
            return Math.Max(minimum, Math.Min(maximum, value));
        }

        private readonly List<byte> parameters = new List<byte>();
        private byte currentCommand;
        private byte memoryAccessControl;
        private byte firstPixelByte;
        private int columnStart;
        private int columnEnd;
        private int pageStart;
        private int pageEnd;
        private int cursorX;
        private int cursorY;
        private bool firstPixelBytePending;
        private bool readSecondBytePending;
        private bool readDummyPending;
        private bool dataMode;
        private bool resetAsserted;

        private const int ScreenWidth = 480;
        private const int ScreenHeight = 320;
        private const int DataCommandInput = 0;
        private const int ResetInput = 1;
        private const byte SoftwareReset = 0x01;
        private const byte DisplayOff = 0x28;
        private const byte DisplayOn = 0x29;
        private const byte ColumnAddressSet = 0x2A;
        private const byte PageAddressSet = 0x2B;
        private const byte MemoryWrite = 0x2C;
        private const byte MemoryRead = 0x2E;
        private const byte MemoryAccessControlCommand = 0x36;
        private const byte MemoryWriteContinue = 0x3C;
        private const byte MemoryReadContinue = 0x3E;
        private const byte FlipBothAxes = 0xC0;
    }
}
