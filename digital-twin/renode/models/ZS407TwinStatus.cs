// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Antmicro.Renode.Core;
using Antmicro.Renode.Exceptions;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Assertions for the source-derived ZS407 executable twin. Legacy UI and
    /// RF methods use addresses tied to the pinned v0.2 ELF; additive release
    /// assertions receive local-symbol addresses from the loaded candidate ELF.
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

        public string AssertPassiveAcquisition(long runtimeInitializedAddress,
            long clockAddress, long ledgerAddress,
            long hardwareQualifiedAddress, long streamQualifiedAddress,
            long captureQualifiedAddress, long streamStorageAddress)
        {
            var failures = new List<string>();
            var initialized = ReadByteFromSram((ulong)runtimeInitializedAddress);
            var clockTimestampUs = ReadQuadWordFromSram((ulong)clockAddress + 8);
            var tickFrequencyHz = ReadDoubleWordFromSram((ulong)clockAddress + 16);
            var clockId = ReadDoubleWordFromSram((ulong)clockAddress + 24);
            var streamId = ReadDoubleWordFromSram((ulong)ledgerAddress);
            var nextSequence = ReadDoubleWordFromSram((ulong)ledgerAddress + 4);
            var completed = ReadDoubleWordFromSram((ulong)ledgerAddress + 8);
            var published = ReadDoubleWordFromSram((ulong)ledgerAddress + 12);
            var dropped = ReadDoubleWordFromSram((ulong)ledgerAddress + 16);
            var invalid = ReadDoubleWordFromSram((ulong)ledgerAddress + 20);
            var lastStartUs = ReadQuadWordFromSram((ulong)ledgerAddress + 24);
            var lastDurationUs = ReadDoubleWordFromSram((ulong)ledgerAddress + 32);
            var lastPoints = ReadWordFromSram((ulong)ledgerAddress + 36);
            var state = ReadByteFromSram((ulong)ledgerAddress + 38);
            var streamStorage = ReadDoubleWordFromSram((ulong)streamStorageAddress);

            Require(initialized == 1, $"runtime initialized={initialized}", failures);
            Require(tickFrequencyHz == 10000,
                $"clock tick frequency {tickFrequencyHz} != 10000", failures);
            Require(clockId == 0x5A533430,
                $"clock ID 0x{clockId:X8} is invalid", failures);
            Require(clockTimestampUs > 0, "clock timestamp was not advanced", failures);
            Require(streamId == 0x04070001,
                $"stream ID 0x{streamId:X8} is invalid", failures);
            Require(nextSequence > 0 && completed > 0,
                $"no completed sweep was ledgered ({nextSequence}/{completed})", failures);
            Require(nextSequence == completed,
                $"sequence {nextSequence} != completed {completed}", failures);
            Require(published == 0 && dropped == 0 && invalid == 0,
                $"locked counters published={published} dropped={dropped} invalid={invalid}", failures);
            Require(lastStartUs > 0 && lastDurationUs > 0,
                $"invalid timing start={lastStartUs} duration={lastDurationUs}", failures);
            Require(lastPoints >= MinimumSweepPoints && lastPoints <= MaximumSweepPoints,
                $"last point count {lastPoints} is invalid", failures);
            Require(state == 0, $"locked acquisition state {state} != 0", failures);
            Require(ReadByteFromSram((ulong)hardwareQualifiedAddress) == 0,
                "hardware qualification latch changed", failures);
            Require(ReadByteFromSram((ulong)streamQualifiedAddress) == 0,
                "stream qualification latch changed", failures);
            Require(ReadByteFromSram((ulong)captureQualifiedAddress) == 0,
                "capture qualification latch changed", failures);
            Require(streamStorage == 0,
                $"locked stream leased memory 0x{streamStorage:X8}", failures);
            ThrowIfAny("passive acquisition", failures);
            return $"ZS407_TWIN_PASSIVE=PASS sequence={nextSequence} "
                + $"start_us={lastStartUs} duration_us={lastDurationUs} "
                + $"points={lastPoints} clock_us={clockTimestampUs} locks=closed";
        }

        public string Report()
        {
            return $"ZS407_TWIN_STATUS spi={Get<ulong>(fabric, "BusTransfers")} pixels={Get<ulong>(display, "PixelWrites")} "
                + $"nonblack={Get<uint>(display, "NonBlackPixels")} frame=0x{Get<ulong>(display, "FramebufferHash"):X16} "
                + $"si4468_commands={Get<ulong>(receiver, "CommandCount")} si4468_state=0x{Get<byte>(receiver, "State"):X2} "
                + $"rssi={Get<byte>(receiver, "MinimumRssiRaw")}..{Get<byte>(receiver, "PeakRssiRaw")} "
                + $"max2871_hz={Get<double>(synthesizer, "FrequencyHz"):F0} attenuation_db={Get<double>(attenuator, "AttenuationDb"):F1}";
        }

        public string ConfigureAnalyzer(long startHz, long stopHz, int points,
            int rbwX10, int attenuationX2, int autoAttenuation,
            int sweepTimeUs, int detector, int spur, int lna, int avoid,
            int trigger, double triggerLevelDbm)
        {
            if(startHz < 0 || stopHz < startHz || stopHz > MaximumAnalyzerFrequencyHz)
            {
                throw new RecoverableException("ZS407 twin analyzer frequency range is invalid");
            }
            if(points < MinimumSweepPoints || points > MaximumSweepPoints)
            {
                throw new RecoverableException($"ZS407 twin points {points} outside {MinimumSweepPoints}..{MaximumSweepPoints}");
            }
            if(rbwX10 < 0 || rbwX10 > MaximumRbwX10)
            {
                throw new RecoverableException("ZS407 twin RBW is outside the firmware range");
            }
            if(attenuationX2 < 0 || attenuationX2 > MaximumAttenuationX2 || (autoAttenuation != 0 && autoAttenuation != 1))
            {
                throw new RecoverableException("ZS407 twin attenuation configuration is invalid");
            }
            if(sweepTimeUs != 0 && (sweepTimeUs < 3000 || sweepTimeUs > 60000000)
                || detector < 0 || detector > 7 || spur < 0 || spur > 2
                || (lna != 0 && lna != 1) || avoid < 0 || avoid > 2
                || trigger < 0 || trigger > 2 || triggerLevelDbm < -174.0 || triggerLevelDbm > 30.0)
            {
                throw new RecoverableException("ZS407 twin analyzer option configuration is invalid");
            }

            var count = (ulong)(points - 1);
            var span = (ulong)(stopHz - startHz);
            var delta = span / count;
            var error = span % count;

            WriteByteToSram(Setting + SettingMode, AnalyzerLowMode);
            WriteByteToSram(Setting + SettingMute, 1);
            WriteByteToSram(Setting + SettingAutoAttenuation, (byte)autoAttenuation);
            WriteWordToSram(Setting + SettingAttenuationX2, (ushort)attenuationX2);
            WriteWordToSram(Setting + SettingSweepPoints, (ushort)points);
            WriteWordToSram(Setting + SettingFrequencyMode, 0);
            WriteDoubleWordToSram(Setting + SettingRbwX10, (uint)rbwX10);
            WriteDoubleWordToSram(Setting + SettingSweepTimeUs, (uint)sweepTimeUs);
            WriteByteToSram(Setting + SettingAverage, (byte)detector);
            WriteByteToSram(Setting + SettingSpurRemoval, (byte)spur);
            WriteByteToSram(Setting + SettingExtraLna, (byte)lna);
            WriteDoubleWordToSram(AvoidSetting, (uint)avoid);
            WriteByteToSram(Setting + SettingTrigger, (byte)trigger);
            WriteFloatToSram(Setting + SettingTriggerLevel, (float)triggerLevelDbm);
            WriteQuadWordToSram(Setting + SettingFrequencyStep, delta);
            WriteQuadWordToSram(Setting + SettingFrequency0, (ulong)startHz);
            WriteQuadWordToSram(Setting + SettingFrequency1, (ulong)stopHz);
            WriteQuadWordToSram(FrequencyStart, (ulong)startHz);
            WriteQuadWordToSram(FrequencyStop, (ulong)stopHz);
            WriteWordToSram(FrequencyCount, (ushort)count);
            WriteQuadWordToSram(FrequencyDelta, delta);
            WriteQuadWordToSram(FrequencyError, error);
            WriteQuadWordToSram(FrequencyStartInternal, (ulong)startHz);

            for(var index = 0; index < MaximumSweepPoints; index++)
            {
                var frequency = index < points
                    ? (ulong)startHz + delta * (ulong)index + (count / 2 + error * (ulong)index) / count
                    : 0UL;
                WriteQuadWordToSram(FrequencyCache + (ulong)(index * sizeof(ulong)), frequency);
            }

            WriteByteToSram(Completed, 0);
            WriteByteToSram(Dirty, 1);
            WriteByteToSram(ScanDirty, 1);
            Invoke(receiver, "ResetRssiStatistics");
            analyzerStartHz = (ulong)startHz;
            analyzerStopHz = (ulong)stopHz;
            analyzerPoints = points;
            return $"ZS407_TWIN_ANALYZER=CONFIGURED start={startHz} stop={stopHz} points={points} rbw_x10={rbwX10} attenuation_x2={attenuationX2} auto={autoAttenuation} sweep_us={sweepTimeUs} detector={detector} spur={spur} lna={lna} avoid={avoid} trigger={trigger}";
        }

        public string ConfigureGenerator(long frequencyHz, double levelDbm,
            int mixerOutput, int modulation, double modulationFrequencyHz,
            int amDepthPercent, int fmDeviationHz, int enabled)
        {
            if(frequencyHz < 1 || frequencyHz > MaximumAnalyzerFrequencyHz)
            {
                throw new RecoverableException("ZS407 twin generator frequency is invalid");
            }
            if(levelDbm < -115.0 || levelDbm > -18.5 || (mixerOutput != 0 && mixerOutput != 1)
                || modulation < 0 || modulation > 2 || modulationFrequencyHz < 1 || modulationFrequencyHz > 10000
                || amDepthPercent < 0 || amDepthPercent > 100 || fmDeviationHz < 1000 || fmDeviationHz > 300000
                || (enabled != 0 && enabled != 1))
            {
                throw new RecoverableException("ZS407 twin generator configuration is invalid");
            }

            WriteByteToSram(Setting + SettingMode, GeneratorLowMode);
            WriteByteToSram(Setting + SettingMute, (byte)(enabled == 1 ? 0 : 1));
            WriteByteToSram(Setting + SettingMixerOutput, (byte)mixerOutput);
            WriteByteToSram(Setting + SettingModulation, (byte)modulation);
            WriteFloatToSram(Setting + SettingModulationFrequency, (float)modulationFrequencyHz);
            WriteWordToSram(Setting + SettingModulationDepthX100, (ushort)(amDepthPercent * 100));
            WriteWordToSram(Setting + SettingModulationDeviationDiv100, (ushort)(fmDeviationHz / 100));
            WriteFloatToSram(Setting + SettingLevel, (float)levelDbm);
            WriteQuadWordToSram(Setting + SettingFrequencyStep, 0);
            WriteQuadWordToSram(Setting + SettingFrequency0, (ulong)frequencyHz);
            WriteQuadWordToSram(Setting + SettingFrequency1, (ulong)frequencyHz);
            WriteWordToSram(Setting + SettingSweepPoints, MinimumSweepPoints);
            WriteWordToSram(FrequencyCount, MinimumSweepPoints - 1);
            WriteQuadWordToSram(FrequencyDelta, 0);
            WriteQuadWordToSram(FrequencyError, 0);
            WriteQuadWordToSram(FrequencyStartInternal, (ulong)frequencyHz);
            for(var index = 0; index < MaximumSweepPoints; index++)
            {
                WriteQuadWordToSram(FrequencyCache + (ulong)(index * sizeof(ulong)), index < MinimumSweepPoints ? (ulong)frequencyHz : 0UL);
            }
            WriteByteToSram(Dirty, 1);
            WriteByteToSram(ScanDirty, 1);
            return $"ZS407_TWIN_GENERATOR=CONFIGURED frequency={frequencyHz} level={levelDbm:F1} mixer={mixerOutput} modulation={modulation} enabled={enabled}";
        }

        public string ExportSweep()
        {
            if(analyzerPoints < MinimumSweepPoints)
            {
                throw new RecoverableException("ZS407 twin analyzer has not been configured through the bridge");
            }
            if(ReadByteFromSram(Completed) == 0)
            {
                throw new RecoverableException("ZS407 twin firmware has not completed the requested sweep");
            }
            var bytes = new byte[analyzerPoints * sizeof(float)];
            for(var index = 0; index < analyzerPoints; index++)
            {
                var raw = ReadDoubleWordFromSram(Measured + (ulong)(index * sizeof(float)));
                var value = BitConverter.ToSingle(BitConverter.GetBytes(raw), 0);
                if(float.IsNaN(value) || float.IsInfinity(value) || value < -300.0f || value > 100.0f)
                {
                    throw new RecoverableException($"ZS407 twin measured[{index}] is invalid: {value}");
                }
                Buffer.BlockCopy(BitConverter.GetBytes(raw), 0, bytes, index * sizeof(float), sizeof(float));
            }
            var encoded = Convert.ToBase64String(bytes);
            return $"ZS407_TWIN_SWEEP start={analyzerStartHz} stop={analyzerStopHz} points={analyzerPoints} rbw_hz={ReadWordFromSram(ActualRbwX10) * 100} sequence={ReadByteFromSram(SweepCounter)} power_f32le={encoded}";
        }

        public string SaveScreenRaw(string path)
        {
            if(string.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path))
            {
                throw new RecoverableException("ZS407 twin screen path must be absolute");
            }
            Invoke(display, "SaveRgb565LittleEndian", path);
            var size = new FileInfo(path).Length;
            if(size != ScreenWidth * ScreenHeight * 2)
            {
                throw new RecoverableException($"ZS407 twin screen has {size} bytes");
            }
            return $"ZS407_TWIN_SCREEN=SAVED bytes={size} frame=0x{Get<ulong>(display, "FramebufferHash"):X16}";
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

        private static void Invoke(IPeripheral peripheral, string methodName, params object[] arguments)
        {
            var method = peripheral.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public);
            if(method == null)
            {
                throw new RecoverableException($"ZS407 twin model {peripheral.GetType().Name} has no {methodName} method");
            }
            method.Invoke(peripheral, arguments);
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

        private ulong ReadQuadWordFromSram(ulong address)
        {
            return ReadDoubleWordFromSram(address)
                | ((ulong)ReadDoubleWordFromSram(address + 4) << 32);
        }

        private void WriteByteToSram(ulong address, byte value)
        {
            machine.GetSystemBus(this).WriteByte(address, value, this);
        }

        private void WriteWordToSram(ulong address, ushort value)
        {
            machine.GetSystemBus(this).WriteWord(address, value, this);
        }

        private void WriteDoubleWordToSram(ulong address, uint value)
        {
            machine.GetSystemBus(this).WriteDoubleWord(address, value, this);
        }

        private void WriteQuadWordToSram(ulong address, ulong value)
        {
            WriteDoubleWordToSram(address, (uint)(value & 0xFFFFFFFFUL));
            WriteDoubleWordToSram(address + 4, (uint)(value >> 32));
        }

        private void WriteFloatToSram(ulong address, float value)
        {
            WriteDoubleWordToSram(address, BitConverter.ToUInt32(BitConverter.GetBytes(value), 0));
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
        private ulong analyzerStartHz;
        private ulong analyzerStopHz;
        private int analyzerPoints;

        private const ulong ChibiOsCurrentThread = 0x20001698;
        private const ulong LastTouchX = 0x200071F6;
        private const ulong LastTouchY = 0x200071F8;
        private const ulong UiMode = 0x200072E1;
        private const ulong Setting = 0x20004CE0;
        private const ulong Measured = 0x2000289C;
        private const ulong ActualRbwX10 = 0x200020EC;
        private const ulong Dirty = 0x20001330;
        private const ulong ScanDirty = 0x200013E4;
        private const ulong Completed = 0x200022DC;
        private const ulong SweepCounter = 0x20005378;
        private const ulong AvoidSetting = 0x200022BC;
        private const ulong FrequencyStart = 0x20002840;
        private const ulong FrequencyStop = 0x20002848;
        private const ulong FrequencyCount = 0x2000208E;
        private const ulong FrequencyDelta = 0x20002090;
        private const ulong FrequencyError = 0x20002098;
        private const ulong FrequencyStartInternal = 0x200020A0;
        private const ulong FrequencyCache = 0x10000000;
        private const ulong SettingAutoAttenuation = 5;
        private const ulong SettingMute = 8;
        private const ulong SettingMode = 408;
        private const ulong SettingLna = 412;
        private const ulong SettingModulation = 413;
        private const ulong SettingTrigger = 414;
        private const ulong SettingAverage = 422;
        private const ulong SettingSpurRemoval = 431;
        private const ulong SettingSweepPoints = 458;
        private const ulong SettingAttenuationX2 = 460;
        private const ulong SettingFrequencyMode = 466;
        private const ulong SettingModulationDepthX100 = 468;
        private const ulong SettingModulationDeviationDiv100 = 470;
        private const ulong SettingRbwX10 = 496;
        private const ulong SettingModulationFrequency = 520;
        private const ulong SettingTriggerLevel = 536;
        private const ulong SettingLevel = 540;
        private const ulong SettingFrequencyStep = 560;
        private const ulong SettingFrequency0 = 568;
        private const ulong SettingFrequency1 = 576;
        private const ulong SettingSweepTimeUs = 1512;
        private const ulong SettingExtraLna = 1533;
        private const ulong SettingMixerOutput = 1545;
        private const long MaximumAnalyzerFrequencyHz = 17922600000L;
        private const int MinimumSweepPoints = 20;
        private const int MaximumSweepPoints = 450;
        private const int MaximumRbwX10 = 8500;
        private const int MaximumAttenuationX2 = 62;
        private const byte AnalyzerLowMode = 0;
        private const byte GeneratorLowMode = 2;
        private const int ScreenWidth = 480;
        private const int ScreenHeight = 320;
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
