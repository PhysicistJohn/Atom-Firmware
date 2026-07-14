// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Antmicro.Renode.Core;
using Antmicro.Renode.Exceptions;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// STM32F303xC USB FS device controller and deterministic host fixture.
    ///
    /// The firmware owns the endpoint registers, packet-memory descriptors,
    /// USB state machine and CDC implementation. Host* methods only inject bus
    /// tokens and acknowledge packets, just like a physical USB host.
    /// </summary>
    public sealed class STM32F303UsbDevice : IBytePeripheral,
        IWordPeripheral, IDoubleWordPeripheral, IKnownSize
    {
        public STM32F303UsbDevice(IMachine machine)
        {
            this.machine = machine;
            IRQ = new GPIO();
            Reset();
        }

        public long Size => 0x400;

        public GPIO IRQ { get; }

        public int Address => (int)(deviceAddress & DeviceAddressMask);

        public bool DeviceEnabled => (deviceAddress & DeviceEnable) != 0
            && (control & (ControlPowerDown | ControlForceReset)) == 0;

        public ulong SetupPackets { get; private set; }

        public ulong OutPackets { get; private set; }

        public ulong InPackets { get; private set; }

        public ulong BusResets { get; private set; }

        public ulong SuspendEvents { get; private set; }

        public ulong WakeupEvents { get; private set; }

        public string CapturedText => Encoding.ASCII.GetString(captured.ToArray());

        public void Reset()
        {
            Array.Clear(endpoints, 0, endpoints.Length);
            control = ControlForceReset;
            globalEvents = 0;
            frameNumber = 0;
            deviceAddress = 0;
            bufferTable = 0;
            lpmControl = 0;
            batteryControl = 0;
            SetupPackets = 0;
            OutPackets = 0;
            InPackets = 0;
            BusResets = 0;
            SuspendEvents = 0;
            WakeupEvents = 0;
            captured.Clear();
            IRQ.Unset();
        }

        public byte ReadByte(long offset)
        {
            var aligned = offset & ~3L;
            var shift = (int)((offset & 3L) * 8);
            return (byte)(ReadDoubleWord(aligned) >> shift);
        }

        public void WriteByte(long offset, byte value)
        {
            var aligned = offset & ~3L;
            var shift = (int)((offset & 3L) * 8);
            var mask = 0xFFu << shift;
            WriteDoubleWord(aligned,
                (ReadDoubleWord(aligned) & ~mask) | ((uint)value << shift));
        }

        public ushort ReadWord(long offset)
        {
            if((offset & 3L) == 3L)
            {
                return (ushort)(ReadByte(offset) | (ReadByte(offset + 1) << 8));
            }
            var aligned = offset & ~3L;
            return (ushort)(ReadDoubleWord(aligned) >> (int)((offset & 3L) * 8));
        }

        public void WriteWord(long offset, ushort value)
        {
            if((offset & 3L) == 3L)
            {
                WriteByte(offset, (byte)value);
                WriteByte(offset + 1, (byte)(value >> 8));
                return;
            }
            var aligned = offset & ~3L;
            var shift = (int)((offset & 3L) * 8);
            var mask = 0xFFFFu << shift;
            WriteDoubleWord(aligned,
                (ReadDoubleWord(aligned) & ~mask) | ((uint)value << shift));
        }

        public uint ReadDoubleWord(long offset)
        {
            if(offset >= Endpoint0 && offset <= Endpoint7 && (offset & 3) == 0)
            {
                return endpoints[offset / 4];
            }
            switch(offset)
            {
                case Control:
                    return control;
                case InterruptStatus:
                    return ComposeInterruptStatus();
                case FrameNumber:
                    return frameNumber;
                case DeviceAddress:
                    return deviceAddress;
                case BufferTable:
                    return bufferTable;
                case LpmControl:
                    return lpmControl;
                case BatteryControl:
                    return batteryControl;
                default:
                    return 0;
            }
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset >= Endpoint0 && offset <= Endpoint7 && (offset & 3) == 0)
            {
                WriteEndpoint((int)(offset / 4), (ushort)value);
                return;
            }
            switch(offset)
            {
                case Control:
                    control = (ushort)value;
                    if((control & ControlForceReset) != 0)
                    {
                        Array.Clear(endpoints, 0, endpoints.Length);
                        globalEvents = 0;
                        deviceAddress = 0;
                    }
                    break;
                case InterruptStatus:
                    // Global event flags are cleared by writing zero. CTR,
                    // DIR and EP_ID are endpoint-derived and read-only.
                    globalEvents &= (ushort)value;
                    break;
                case FrameNumber:
                    break;
                case DeviceAddress:
                    deviceAddress = (ushort)(value & 0xFF);
                    break;
                case BufferTable:
                    bufferTable = (ushort)(value & 0xFFF8);
                    break;
                case LpmControl:
                    lpmControl = value;
                    break;
                case BatteryControl:
                    batteryControl = value;
                    break;
            }
            UpdateInterrupt();
        }

        public string HostReset()
        {
            EnsureEnabled("reset");
            Array.Clear(endpoints, 0, endpoints.Length);
            deviceAddress = DeviceEnable;
            globalEvents |= InterruptReset;
            BusResets++;
            UpdateInterrupt();
            return $"ZS407_TWIN_USB=RESET count={BusResets}";
        }

        public string HostSuspend()
        {
            EnsureEnabled("suspend");
            globalEvents |= InterruptSuspend;
            SuspendEvents++;
            UpdateInterrupt();
            return $"ZS407_TWIN_USB=SUSPEND count={SuspendEvents}";
        }

        public string HostWakeup()
        {
            globalEvents |= InterruptWakeup;
            WakeupEvents++;
            UpdateInterrupt();
            return $"ZS407_TWIN_USB=WAKEUP count={WakeupEvents}";
        }

        public string HostSof(int frames = 1)
        {
            if(frames < 1 || frames > 1000)
            {
                throw new RecoverableException("ZS407 twin USB SOF count must be 1..1000");
            }
            frameNumber = (ushort)((frameNumber + frames) & FrameNumberMask);
            globalEvents |= InterruptSof;
            UpdateInterrupt();
            return $"ZS407_TWIN_USB=SOF frame={frameNumber}";
        }

        public string HostSetup(string hexadecimal)
        {
            var data = ParseHex(hexadecimal);
            if(data.Length != 8)
            {
                throw new RecoverableException("ZS407 twin USB SETUP packets must contain 8 bytes");
            }
            WriteHostPacket(0, data, true);
            SetupPackets++;
            return $"ZS407_TWIN_USB=SETUP count={SetupPackets} data={ToHex(data)}";
        }

        public string HostOut(int endpoint, string hexadecimal)
        {
            var data = ParseHex(hexadecimal);
            WriteHostPacket(endpoint, data, false);
            OutPackets++;
            return $"ZS407_TWIN_USB=OUT ep={endpoint} bytes={data.Length} count={OutPackets}";
        }

        public string HostIn(int endpoint)
        {
            ValidateEndpoint(endpoint);
            EnsureEnabled("IN token");
            var epr = endpoints[endpoint];
            if((epr & EndpointTxStatusMask) != EndpointTxValid)
            {
                throw new RecoverableException($"ZS407 twin USB endpoint {endpoint} IN is not VALID (EPR=0x{epr:X4})");
            }

            var descriptor = DescriptorAddress(endpoint);
            var usbAddress = (ushort)(ReadPacketDoubleWord(descriptor + TxAddressOffset) & 0xFFFF);
            var count = (int)(ReadPacketDoubleWord(descriptor + TxCountOffset) & PacketCountMask);
            if(count > MaximumPacketSize)
            {
                throw new RecoverableException($"ZS407 twin USB endpoint {endpoint} TX count {count} exceeds {MaximumPacketSize}");
            }
            var data = ReadPacketData(usbAddress, count);
            captured.AddRange(data);
            InPackets++;

            // Successful IN completion changes VALID to NAK and raises CTR_TX.
            endpoints[endpoint] = (ushort)((epr & ~EndpointTxStatusMask)
                | EndpointTxNak | EndpointCtrTx);
            UpdateInterrupt();
            return $"ZS407_TWIN_USB=IN ep={endpoint} bytes={count} count={InPackets} data={ToHex(data)}";
        }

        public string HostPollIn(int endpoint)
        {
            ValidateEndpoint(endpoint);
            if((endpoints[endpoint] & EndpointTxStatusMask) != EndpointTxValid)
            {
                return $"ZS407_TWIN_USB=NAK ep={endpoint}";
            }
            return HostIn(endpoint);
        }

        public string ClearCapture()
        {
            captured.Clear();
            return "ZS407_TWIN_USB_CAPTURE=cleared";
        }

        public string Report()
        {
            return $"ZS407_TWIN_USB_STATUS cntr=0x{control:X4} istr=0x{ComposeInterruptStatus():X4} "
                + $"daddr=0x{deviceAddress:X2} btable=0x{bufferTable:X3} "
                + $"ep0=0x{endpoints[0]:X4} ep1=0x{endpoints[1]:X4} "
                + $"ep2=0x{endpoints[2]:X4} setup={SetupPackets} out={OutPackets} in={InPackets}";
        }

        public string AssertCaptureContains(string expected)
        {
            if(expected == null || !CapturedText.Contains(expected))
            {
                throw new RecoverableException($"ZS407 twin USB capture does not contain '{expected}': '{Escape(CapturedText)}'");
            }
            return $"ZS407_TWIN_USB_CDC=PASS contains={expected} bytes={captured.Count}";
        }

        public string AssertCaptureHexContains(string expectedHexadecimal)
        {
            var expected = ToHex(ParseHex(expectedHexadecimal));
            var actual = ToHex(captured.ToArray());
            if(!actual.Contains(expected))
            {
                throw new RecoverableException($"ZS407 twin USB capture does not contain hex {expected}: {actual}");
            }
            return $"ZS407_TWIN_USB_DESCRIPTOR=PASS contains={expected} bytes={captured.Count}";
        }

        public string AssertEndpointStalled(int endpoint)
        {
            ValidateEndpoint(endpoint);
            var epr = endpoints[endpoint];
            var txStalled = (epr & EndpointTxStatusMask) == EndpointTxStall;
            var rxStalled = (epr & EndpointRxStatusMask) == EndpointRxStall;
            if(!txStalled && !rxStalled)
            {
                throw new RecoverableException($"ZS407 twin USB endpoint {endpoint} was not stalled (EPR=0x{epr:X4})");
            }
            return $"ZS407_TWIN_USB_STALL=PASS ep={endpoint} epr=0x{epr:X4}";
        }

        public string AssertEvents(int resets, int suspends, int wakeups)
        {
            if(BusResets != (ulong)resets || SuspendEvents != (ulong)suspends
                || WakeupEvents != (ulong)wakeups)
            {
                throw new RecoverableException("ZS407 twin USB event assertion failed: "
                    + $"reset={BusResets}/{resets} suspend={SuspendEvents}/{suspends} "
                    + $"wakeup={WakeupEvents}/{wakeups}");
            }
            return $"ZS407_TWIN_USB_EVENTS=PASS reset={BusResets} suspend={SuspendEvents} wakeup={WakeupEvents}";
        }

        public string AssertDevice(int expectedAddress, int requireDataEndpoints)
        {
            if(expectedAddress < 0 || expectedAddress > 127
                || (requireDataEndpoints != 0 && requireDataEndpoints != 1))
            {
                throw new RecoverableException("ZS407 twin USB device assertion arguments are invalid");
            }
            var failures = new List<string>();
            if(!DeviceEnabled)
            {
                failures.Add("device controller is not enabled");
            }
            if(Address != expectedAddress)
            {
                failures.Add($"address {Address} != {expectedAddress}");
            }
            if(requireDataEndpoints == 1)
            {
                if((endpoints[1] & EndpointTypeMask) != EndpointTypeBulk)
                {
                    failures.Add($"EP1 is not bulk (EPR=0x{endpoints[1]:X4})");
                }
                if((endpoints[2] & EndpointTypeMask) != EndpointTypeInterrupt)
                {
                    failures.Add($"EP2 is not interrupt (EPR=0x{endpoints[2]:X4})");
                }
            }
            if(failures.Count != 0)
            {
                throw new RecoverableException("ZS407 twin USB device assertion failed: "
                    + string.Join("; ", failures));
            }
            return $"ZS407_TWIN_USB_ENUM=PASS address={Address} ep1=0x{endpoints[1]:X4} ep2=0x{endpoints[2]:X4}";
        }

        private void WriteEndpoint(int endpoint, ushort value)
        {
            var current = endpoints[endpoint];
            var next = (ushort)((current & (EndpointReadOnlyMask | EndpointToggleMask))
                | (value & EndpointNormalWriteMask));
            next ^= (ushort)(value & EndpointToggleMask);

            if((value & EndpointCtrTx) == 0)
            {
                next &= unchecked((ushort)~EndpointCtrTx);
            }
            else
            {
                next |= (ushort)(current & EndpointCtrTx);
            }
            if((value & EndpointCtrRx) == 0)
            {
                next &= unchecked((ushort)~(EndpointCtrRx | EndpointSetup));
            }
            else
            {
                next |= (ushort)(current & (EndpointCtrRx | EndpointSetup));
            }
            endpoints[endpoint] = next;
            UpdateInterrupt();
        }

        private void WriteHostPacket(int endpoint, byte[] data, bool setup)
        {
            ValidateEndpoint(endpoint);
            EnsureEnabled(setup ? "SETUP packet" : "OUT token");
            var epr = endpoints[endpoint];
            if(!setup && (epr & EndpointRxStatusMask) != EndpointRxValid)
            {
                throw new RecoverableException($"ZS407 twin USB endpoint {endpoint} OUT is not VALID (EPR=0x{epr:X4})");
            }
            if(data.Length > MaximumPacketSize)
            {
                throw new RecoverableException($"ZS407 twin USB packet length {data.Length} exceeds {MaximumPacketSize}");
            }

            var descriptor = DescriptorAddress(endpoint);
            var usbAddress = (ushort)(ReadPacketDoubleWord(descriptor + RxAddressOffset) & 0xFFFF);
            WritePacketData(usbAddress, data);
            var rxCount = ReadPacketDoubleWord(descriptor + RxCountOffset);
            WritePacketDoubleWord(descriptor + RxCountOffset,
                (rxCount & ~PacketCountMask) | (uint)data.Length);

            endpoints[endpoint] = (ushort)((epr & ~EndpointRxStatusMask)
                | EndpointRxNak | EndpointCtrRx
                | (setup ? EndpointSetup : 0));
            UpdateInterrupt();
        }

        private uint ComposeInterruptStatus()
        {
            for(var endpoint = 0; endpoint < endpoints.Length; endpoint++)
            {
                var epr = endpoints[endpoint];
                if((epr & EndpointCtrRx) != 0)
                {
                    return (uint)(globalEvents | InterruptCtr | InterruptDirection
                        | endpoint);
                }
                if((epr & EndpointCtrTx) != 0)
                {
                    return (uint)(globalEvents | InterruptCtr | endpoint);
                }
            }
            return globalEvents;
        }

        private void UpdateInterrupt()
        {
            var status = ComposeInterruptStatus();
            var active = ((status & InterruptCtr) != 0 && (control & ControlCtrMask) != 0)
                || ((status & InterruptReset) != 0 && (control & ControlResetMask) != 0)
                || ((status & InterruptSuspend) != 0 && (control & ControlSuspendMask) != 0)
                || ((status & InterruptWakeup) != 0 && (control & ControlWakeupMask) != 0)
                || ((status & InterruptSof) != 0 && (control & ControlSofMask) != 0)
                || ((status & InterruptError) != 0 && (control & ControlErrorMask) != 0)
                || ((status & InterruptPmaOverrun) != 0 && (control & ControlPmaOverrunMask) != 0);
            IRQ.Set(active);
        }

        private ulong DescriptorAddress(int endpoint)
        {
            return PacketMemoryBase + bufferTable + (ulong)(endpoint * DescriptorSize);
        }

        private uint ReadPacketDoubleWord(ulong address)
        {
            return machine.GetSystemBus(this).ReadDoubleWord(address, this);
        }

        private void WritePacketDoubleWord(ulong address, uint value)
        {
            machine.GetSystemBus(this).WriteDoubleWord(address, value, this);
        }

        private byte[] ReadPacketData(ushort usbAddress, int count)
        {
            var result = new byte[count];
            for(var index = 0; index < count; index += 2)
            {
                var word = ReadPacketDoubleWord(PacketMemoryBase
                    + (ulong)(usbAddress * 2 + index * 2));
                result[index] = (byte)word;
                if(index + 1 < count)
                {
                    result[index + 1] = (byte)(word >> 8);
                }
            }
            return result;
        }

        private void WritePacketData(ushort usbAddress, byte[] data)
        {
            for(var index = 0; index < data.Length; index += 2)
            {
                uint word = data[index];
                if(index + 1 < data.Length)
                {
                    word |= (uint)data[index + 1] << 8;
                }
                WritePacketDoubleWord(PacketMemoryBase
                    + (ulong)(usbAddress * 2 + index * 2), word);
            }
        }

        private void EnsureEnabled(string operation)
        {
            if(!DeviceEnabled)
            {
                throw new RecoverableException($"ZS407 twin USB cannot inject {operation}: device controller is disabled");
            }
        }

        private static void ValidateEndpoint(int endpoint)
        {
            if(endpoint < 0 || endpoint >= EndpointCount)
            {
                throw new RecoverableException($"ZS407 twin USB endpoint {endpoint} outside 0..{EndpointCount - 1}");
            }
        }

        private static byte[] ParseHex(string value)
        {
            if(value == null)
            {
                throw new RecoverableException("ZS407 twin USB packet cannot be null");
            }
            var compact = value.Replace(" ", string.Empty)
                .Replace("_", string.Empty).Replace("-", string.Empty);
            if((compact.Length & 1) != 0)
            {
                throw new RecoverableException("ZS407 twin USB hexadecimal packet has odd length");
            }
            var data = new byte[compact.Length / 2];
            for(var index = 0; index < data.Length; index++)
            {
                if(!byte.TryParse(compact.Substring(index * 2, 2),
                    NumberStyles.HexNumber, CultureInfo.InvariantCulture,
                    out data[index]))
                {
                    throw new RecoverableException("ZS407 twin USB packet contains invalid hexadecimal data");
                }
            }
            return data;
        }

        private static string ToHex(byte[] data)
        {
            var builder = new StringBuilder(data.Length * 2);
            foreach(var value in data)
            {
                builder.Append(value.ToString("x2", CultureInfo.InvariantCulture));
            }
            return builder.ToString();
        }

        private static string Escape(string value)
        {
            return value.Replace("\r", "\\r").Replace("\n", "\\n");
        }

        private readonly IMachine machine;
        private readonly ushort[] endpoints = new ushort[EndpointCount];
        private readonly List<byte> captured = new List<byte>();
        private ushort control;
        private ushort globalEvents;
        private ushort frameNumber;
        private ushort deviceAddress;
        private ushort bufferTable;
        private uint lpmControl;
        private uint batteryControl;

        private const int EndpointCount = 8;
        private const int MaximumPacketSize = 64;
        private const long Endpoint0 = 0x00;
        private const long Endpoint7 = 0x1C;
        private const long Control = 0x40;
        private const long InterruptStatus = 0x44;
        private const long FrameNumber = 0x48;
        private const long DeviceAddress = 0x4C;
        private const long BufferTable = 0x50;
        private const long LpmControl = 0x54;
        private const long BatteryControl = 0x58;

        private const ushort EndpointAddressMask = 0x000F;
        private const ushort EndpointTxStatusMask = 0x0030;
        private const ushort EndpointTxStall = 0x0010;
        private const ushort EndpointTxNak = 0x0020;
        private const ushort EndpointTxValid = 0x0030;
        private const ushort EndpointDataToggleTx = 0x0040;
        private const ushort EndpointCtrTx = 0x0080;
        private const ushort EndpointKind = 0x0100;
        private const ushort EndpointTypeMask = 0x0600;
        private const ushort EndpointTypeBulk = 0x0000;
        private const ushort EndpointTypeInterrupt = 0x0600;
        private const ushort EndpointSetup = 0x0800;
        private const ushort EndpointRxStatusMask = 0x3000;
        private const ushort EndpointRxStall = 0x1000;
        private const ushort EndpointRxNak = 0x2000;
        private const ushort EndpointRxValid = 0x3000;
        private const ushort EndpointDataToggleRx = 0x4000;
        private const ushort EndpointCtrRx = 0x8000;
        private const ushort EndpointNormalWriteMask = EndpointAddressMask
            | EndpointKind | EndpointTypeMask;
        private const ushort EndpointToggleMask = EndpointTxStatusMask
            | EndpointDataToggleTx | EndpointRxStatusMask | EndpointDataToggleRx;
        private const ushort EndpointReadOnlyMask = EndpointCtrTx
            | EndpointSetup | EndpointCtrRx;

        private const ushort ControlForceReset = 0x0001;
        private const ushort ControlPowerDown = 0x0002;
        private const ushort ControlSofMask = 0x0200;
        private const ushort ControlResetMask = 0x0400;
        private const ushort ControlSuspendMask = 0x0800;
        private const ushort ControlWakeupMask = 0x1000;
        private const ushort ControlErrorMask = 0x2000;
        private const ushort ControlPmaOverrunMask = 0x4000;
        private const ushort ControlCtrMask = 0x8000;

        private const ushort InterruptSof = 0x0200;
        private const ushort InterruptReset = 0x0400;
        private const ushort InterruptSuspend = 0x0800;
        private const ushort InterruptWakeup = 0x1000;
        private const ushort InterruptError = 0x2000;
        private const ushort InterruptPmaOverrun = 0x4000;
        private const ushort InterruptCtr = 0x8000;
        private const ushort InterruptDirection = 0x0010;
        private const ushort FrameNumberMask = 0x07FF;
        private const ushort DeviceAddressMask = 0x007F;
        private const ushort DeviceEnable = 0x0080;

        private const ulong PacketMemoryBase = 0x40006000;
        private const int DescriptorSize = 16;
        private const ulong TxAddressOffset = 0;
        private const ulong TxCountOffset = 4;
        private const ulong RxAddressOffset = 8;
        private const ulong RxCountOffset = 12;
        private const uint PacketCountMask = 0x03FF;
    }
}
