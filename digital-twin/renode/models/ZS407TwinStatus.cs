// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Exceptions;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Assertions for the immutable v0.2.0 ZS407 executable twin.
    /// Static SRAM addresses are deliberately tied to the pinned ELF and are
    /// guarded by host-side binary and ELF hashes before a scenario starts.
    /// </summary>
    public sealed class ZS407TwinStatus : IDoubleWordPeripheral, IKnownSize
    {
        public ZS407TwinStatus(IMachine machine, IPeripheral fabric,
            IPeripheral display, IPeripheral receiver, IPeripheral synthesizer,
            IPeripheral attenuator, IPeripheral touchAdc)
        {
            this.machine = machine;
            this.fabric = fabric;
            this.display = display;
            this.receiver = receiver;
            this.synthesizer = synthesizer;
            this.attenuator = attenuator;
            this.touchAdc = touchAdc;
        }

        public long Size => 0x100;

        public void Reset()
        {
        }

        public uint ReadDoubleWord(long offset)
        {
            return 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
        }

        public string AssertBooted()
        {
            var failures = new List<string>();
            var busTransfers = Get<ulong>(fabric, "BusTransfers");
            var pixelWrites = Get<ulong>(display, "PixelWrites");
            var nonBlackPixels = Get<uint>(display, "NonBlackPixels");
            var receiverCommands = Get<ulong>(receiver, "CommandCount");
            var receiverState = Get<byte>(receiver, "State");
            var synthesizerWrites = Get<ulong>(synthesizer, "RegisterWrites");
            var synthesizerFrequency = Get<double>(synthesizer, "FrequencyHz");
            var attenuatorLatches = Get<ulong>(attenuator, "LatchCount");
            Require(busTransfers >= MinimumBootBusTransfers,
                $"SPI transfers {busTransfers} < {MinimumBootBusTransfers}", failures);
            Require(Get<bool>(display, "DisplayEnabled"), "display is disabled", failures);
            Require(pixelWrites >= MinimumBootPixelWrites,
                $"pixel writes {pixelWrites} < {MinimumBootPixelWrites}", failures);
            Require(nonBlackPixels >= MinimumBootNonBlackPixels,
                $"non-black pixels {nonBlackPixels} < {MinimumBootNonBlackPixels}", failures);
            Require(receiverCommands >= MinimumBootReceiverCommands,
                $"Si4468 commands {receiverCommands} < {MinimumBootReceiverCommands}", failures);
            Require(receiverState == ReceiverStateReceive,
                $"Si4468 state 0x{receiverState:X2} != RX", failures);
            Require(synthesizerWrites >= MinimumSynthesizerWrites,
                $"synthesizer writes {synthesizerWrites} < {MinimumSynthesizerWrites}", failures);
            Require(synthesizerFrequency > 0,
                "synthesizer frequency was not programmed", failures);
            Require(attenuatorLatches >= MinimumAttenuatorLatches,
                $"attenuator latches {attenuatorLatches} < {MinimumAttenuatorLatches}", failures);
            Require(ReadDoubleWordFromSram(ChibiOsCurrentThread) != 0,
                "ChibiOS current-thread pointer is null", failures);
            ThrowIfAny("boot", failures);

            return $"ZS407_TWIN_BOOT=PASS spi={busTransfers} pixels={pixelWrites} "
                + $"nonblack={nonBlackPixels} si4468={receiverCommands} "
                + $"max2871={synthesizerWrites} pe4302={attenuatorLatches} "
                + $"frame=0x{Get<ulong>(display, "FramebufferHash"):X16}";
        }

        public string AssertMenuOpen()
        {
            var mode = ReadByteFromSram(UiMode);
            if(mode != UiMenu)
            {
                throw new RecoverableException($"ZS407 twin menu assertion failed: UI mode {mode} != {UiMenu}");
            }
            return $"ZS407_TWIN_JOG=PASS ui_mode={mode} frame=0x{Get<ulong>(display, "FramebufferHash"):X16}";
        }

        public string AssertNormalUi()
        {
            var mode = ReadByteFromSram(UiMode);
            if(mode != UiNormal)
            {
                throw new RecoverableException($"ZS407 twin UI assertion failed: UI mode {mode} != {UiNormal}");
            }
            return $"ZS407_TWIN_UI_NORMAL=PASS frame=0x{Get<ulong>(display, "FramebufferHash"):X16}";
        }

        public string AssertTouchAccepted()
        {
            var firmwareX = ReadWordFromSram(LastTouchX);
            var firmwareY = ReadWordFromSram(LastTouchY);
            var injectedX = Get<uint>(touchAdc, "TouchXRaw");
            var injectedY = Get<uint>(touchAdc, "TouchYRaw");
            var failures = new List<string>();
            Require(Get<bool>(touchAdc, "TouchPressed"), "touch stimulus is not pressed", failures);
            Require(Within(firmwareX, injectedX, TouchRawTolerance),
                $"firmware X {firmwareX} != injected {injectedX}", failures);
            Require(Within(firmwareY, injectedY, TouchRawTolerance),
                $"firmware Y {firmwareY} != injected {injectedY}", failures);
            ThrowIfAny("touch", failures);
            return $"ZS407_TWIN_TOUCH=PASS pixel={Get<int>(touchAdc, "TouchXPixel")},{Get<int>(touchAdc, "TouchYPixel")} "
                + $"raw={firmwareX},{firmwareY}";
        }

        public string AssertToneObserved(int minimumPeakRaw)
        {
            var failures = new List<string>();
            var sampleCount = Get<ulong>(receiver, "RssiSampleCount");
            var minimum = Get<byte>(receiver, "MinimumRssiRaw");
            var peak = Get<byte>(receiver, "PeakRssiRaw");
            Require(Get<int>(receiver, "ToneCount") > 0, "RF scene has no tones", failures);
            Require(sampleCount >= MinimumRssiSamples,
                $"RSSI samples {sampleCount} < {MinimumRssiSamples}", failures);
            Require(peak >= minimumPeakRaw,
                $"peak RSSI {peak} < {minimumPeakRaw}", failures);
            Require(minimum < peak,
                $"RSSI did not vary ({minimum}..{peak})", failures);
            ThrowIfAny("RF tone", failures);
            return $"ZS407_TWIN_RF_TONE=PASS samples={sampleCount} "
                + $"range={minimum}..{peak} "
                + $"frame=0x{Get<ulong>(display, "FramebufferHash"):X16}";
        }

        public string Report()
        {
            return $"ZS407_TWIN_STATUS spi={Get<ulong>(fabric, "BusTransfers")} pixels={Get<ulong>(display, "PixelWrites")} "
                + $"nonblack={Get<uint>(display, "NonBlackPixels")} frame=0x{Get<ulong>(display, "FramebufferHash"):X16} "
                + $"si4468_commands={Get<ulong>(receiver, "CommandCount")} si4468_state=0x{Get<byte>(receiver, "State"):X2} "
                + $"rssi={Get<byte>(receiver, "MinimumRssiRaw")}..{Get<byte>(receiver, "PeakRssiRaw")} "
                + $"max2871_hz={Get<double>(synthesizer, "FrequencyHz"):F0} attenuation_db={Get<double>(attenuator, "AttenuationDb"):F1}";
        }

        private static T Get<T>(IPeripheral peripheral, string propertyName)
        {
            var property = peripheral.GetType().GetProperty(propertyName);
            if(property == null)
            {
                throw new RecoverableException($"ZS407 twin model {peripheral.GetType().Name} has no {propertyName} property");
            }
            return (T)Convert.ChangeType(property.GetValue(peripheral), typeof(T));
        }

        private byte ReadByteFromSram(ulong address)
        {
            return machine.GetSystemBus(this).ReadByte(address, this);
        }

        private ushort ReadWordFromSram(ulong address)
        {
            return machine.GetSystemBus(this).ReadWord(address, this);
        }

        private uint ReadDoubleWordFromSram(ulong address)
        {
            return machine.GetSystemBus(this).ReadDoubleWord(address, this);
        }

        private static bool Within(ushort actual, uint expected, uint tolerance)
        {
            return Math.Abs(actual - (long)expected) <= tolerance;
        }

        private static void Require(bool condition, string message,
            ICollection<string> failures)
        {
            if(!condition)
            {
                failures.Add(message);
            }
        }

        private static void ThrowIfAny(string scope, ICollection<string> failures)
        {
            if(failures.Count != 0)
            {
                throw new RecoverableException($"ZS407 twin {scope} assertion failed: "
                    + string.Join("; ", failures));
            }
        }

        private readonly IMachine machine;
        private readonly IPeripheral fabric;
        private readonly IPeripheral display;
        private readonly IPeripheral receiver;
        private readonly IPeripheral synthesizer;
        private readonly IPeripheral attenuator;
        private readonly IPeripheral touchAdc;

        private const ulong ChibiOsCurrentThread = 0x20001698;
        private const ulong LastTouchX = 0x200071F6;
        private const ulong LastTouchY = 0x200071F8;
        private const ulong UiMode = 0x200072E1;
        private const ulong MinimumBootBusTransfers = 900000;
        private const ulong MinimumBootPixelWrites = 400000;
        private const uint MinimumBootNonBlackPixels = 1000;
        private const ulong MinimumBootReceiverCommands = 150;
        private const ulong MinimumSynthesizerWrites = 6;
        private const ulong MinimumAttenuatorLatches = 1;
        private const ulong MinimumRssiSamples = 100;
        private const uint TouchRawTolerance = 4;
        private const byte ReceiverStateReceive = 0x08;
        private const byte UiNormal = 0;
        private const byte UiMenu = 1;
    }
}
