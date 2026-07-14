// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using Antmicro.Renode.Core;
using Antmicro.Renode.Exceptions;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Assertions for a symbol-profiled ZS407 executable twin. The default
    /// addresses describe the immutable v0.2.0 image; alternate ELFs must load
    /// an explicit, generated profile before execution.
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

        public string LoadSymbolProfile(string path)
        {
            if(string.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path))
            {
                throw new RecoverableException("ZS407 twin symbol profile path must be absolute");
            }
            if(!File.Exists(path))
            {
                throw new RecoverableException($"ZS407 twin symbol profile does not exist: {path}");
            }

            var values = new Dictionary<string, ulong>(StringComparer.Ordinal);
            foreach(var rawLine in File.ReadAllLines(path))
            {
                var line = rawLine;
                var comment = line.IndexOf('#');
                if(comment >= 0)
                {
                    line = line.Substring(0, comment);
                }
                line = line.Trim();
                if(line.Length == 0)
                {
                    continue;
                }
                var separator = line.IndexOf('=');
                if(separator <= 0 || separator == line.Length - 1)
                {
                    throw new RecoverableException($"ZS407 twin malformed symbol profile line: {rawLine}");
                }
                var key = line.Substring(0, separator).Trim();
                var encoded = line.Substring(separator + 1).Trim();
                ulong value;
                var isHex = encoded.StartsWith("0x", StringComparison.OrdinalIgnoreCase);
                var digits = isHex ? encoded.Substring(2) : encoded;
                var style = isHex ? NumberStyles.AllowHexSpecifier : NumberStyles.None;
                if(!ulong.TryParse(digits, style, CultureInfo.InvariantCulture, out value))
                {
                    throw new RecoverableException($"ZS407 twin invalid symbol address for {key}: {encoded}");
                }
                if(values.ContainsKey(key))
                {
                    throw new RecoverableException($"ZS407 twin duplicate symbol profile key: {key}");
                }
                values.Add(key, value);
            }

            foreach(var key in values.Keys)
            {
                if(Array.IndexOf(SymbolProfileKeys, key) < 0)
                {
                    throw new RecoverableException($"ZS407 twin unknown symbol profile key: {key}");
                }
            }

            // Resolve and validate the complete profile before mutating any
            // active address, so a malformed file cannot leave a mixed image.
            var chibiOsCurrentThread = GetProfileAddress(values, "chibios_current_thread");
            var lastTouchX = GetProfileAddress(values, "last_touch_x");
            var lastTouchY = GetProfileAddress(values, "last_touch_y");
            var uiMode = GetProfileAddress(values, "ui_mode");
            var setting = GetProfileAddress(values, "setting");
            var sweepMode = GetProfileAddress(values, "sweep_mode");
            var inSelfTest = GetProfileAddress(values, "in_selftest");
            var selfTestStatus = GetProfileAddress(values, "selftest_status");
            var selfTestFailCause = GetProfileAddress(values, "selftest_fail_cause");
            var selfTestWait = GetProfileAddress(values, "selftest_wait");
            var peakFrequency = GetProfileAddress(values, "peak_frequency");
            var peakLevel = GetProfileAddress(values, "peak_level");
            var peakIndex = GetProfileAddress(values, "peak_index");
            var shellFunction = GetProfileAddress(values, "shell_function");
            var shellLine = GetProfileAddress(values, "shell_line");
            var shellNargs = GetProfileAddress(values, "shell_nargs");
            var shellStream = GetProfileAddress(values, "shell_stream");
            var measured = GetProfileAddress(values, "measured");
            var actualRbwX10 = GetProfileAddress(values, "actual_rbw_x10");
            var dirty = GetProfileAddress(values, "dirty");
            var scanDirty = GetProfileAddress(values, "scan_dirty");
            var completed = GetProfileAddress(values, "completed");
            var sweepCounter = GetProfileAddress(values, "sweep_counter");
            var avoidSetting = GetProfileAddress(values, "avoid_setting");
            var frequencyStart = GetProfileAddress(values, "frequency_start");
            var frequencyStop = GetProfileAddress(values, "frequency_stop");
            var frequencyCount = GetProfileAddress(values, "frequency_count");
            var frequencyDelta = GetProfileAddress(values, "frequency_delta");
            var frequencyError = GetProfileAddress(values, "frequency_error");
            var frequencyStartInternal = GetProfileAddress(values, "frequency_start_internal");
            var frequencyCache = GetProfileAddress(values, "frequency_cache", true);

            ChibiOsCurrentThread = chibiOsCurrentThread;
            LastTouchX = lastTouchX;
            LastTouchY = lastTouchY;
            UiMode = uiMode;
            Setting = setting;
            SweepMode = sweepMode;
            InSelfTest = inSelfTest;
            SelfTestStatus = selfTestStatus;
            SelfTestFailCause = selfTestFailCause;
            SelfTestWait = selfTestWait;
            PeakFrequency = peakFrequency;
            PeakLevel = peakLevel;
            PeakIndex = peakIndex;
            ShellFunction = shellFunction;
            ShellLine = shellLine;
            ShellNargs = shellNargs;
            ShellStream = shellStream;
            Measured = measured;
            ActualRbwX10 = actualRbwX10;
            Dirty = dirty;
            ScanDirty = scanDirty;
            Completed = completed;
            SweepCounter = sweepCounter;
            AvoidSetting = avoidSetting;
            FrequencyStart = frequencyStart;
            FrequencyStop = frequencyStop;
            FrequencyCount = frequencyCount;
            FrequencyDelta = frequencyDelta;
            FrequencyError = frequencyError;
            FrequencyStartInternal = frequencyStartInternal;
            FrequencyCache = frequencyCache;
            symbolProfileName = Path.GetFileName(path);

            return $"ZS407_TWIN_SYMBOLS=LOADED profile={symbolProfileName} count={values.Count} "
                + $"setting=0x{Setting:X8} measured=0x{Measured:X8}";
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

        public string SetCalibrationLoopback(int connected, double powerDbm = -35.3)
        {
            if(connected != 0 && connected != 1)
            {
                throw new RecoverableException("ZS407 twin CAL loopback state must be 0 or 1");
            }
            Invoke(receiver, "SetCalibrationPowerDbm", powerDbm);
            Invoke(receiver, "SetCalibrationLoopback", connected == 1);
            return $"ZS407_TWIN_CAL_LOOPBACK={(connected == 1 ? "connected" : "disconnected")} power_dbm={powerDbm:F1}";
        }

        public string RunSelfTestCase(int oneBasedTest)
        {
            if(oneBasedTest < 1 || oneBasedTest > SelfTestCount)
            {
                throw new RecoverableException($"ZS407 twin self-test case {oneBasedTest} outside 1..{SelfTestCount}");
            }
            WriteByteToSram(Setting + SettingTest, 0);
            WriteQuadWordToSram(Setting + SettingTestArgument,
                unchecked((ulong)-(long)oneBasedTest));
            Invoke(receiver, "SetSelfTestFixture", oneBasedTest);
            Invoke(receiver, "ResetRssiStatistics");
            WriteByteToSram(SweepMode, SweepSelfTest);
            return $"ZS407_TWIN_SELFTEST=START case={oneBasedTest}";
        }

        public string AssertSelfTestCase(int oneBasedTest, int expectedStatus = SelfTestPass)
        {
            if(oneBasedTest < 1 || oneBasedTest > SelfTestCount
                || expectedStatus < SelfTestWaiting || expectedStatus > SelfTestCritical)
            {
                throw new RecoverableException("ZS407 twin self-test assertion arguments are invalid");
            }
            var actual = (int)ReadDoubleWordFromSram(SelfTestStatus
                + (ulong)((oneBasedTest - 1) * sizeof(uint)));
            var failures = new List<string>();
            Require(actual == expectedStatus,
                $"case {oneBasedTest} status {actual} != {expectedStatus}", failures);
            Require(ReadByteFromSram(InSelfTest) == 0,
                "firmware did not leave self-test mode", failures);
            Require(ReadByteFromSram(SweepMode) == SweepEnabled,
                $"sweep mode 0x{ReadByteFromSram(SweepMode):X2} was not restored", failures);
            Require(ReadDoubleWordFromSram(SelfTestWait) == 0,
                "single-case self-test remained waiting", failures);
            ThrowIfAny("self-test", failures);
            return $"ZS407_TWIN_SELFTEST=PASS case={oneBasedTest} status={actual}";
        }

        public string AssertSelfTestFailureDetected(int oneBasedTest)
        {
            if(oneBasedTest < 1 || oneBasedTest > SelfTestCount)
            {
                throw new RecoverableException("ZS407 twin self-test failure assertion case is invalid");
            }
            var actual = (int)ReadDoubleWordFromSram(SelfTestStatus
                + (ulong)((oneBasedTest - 1) * sizeof(uint)));
            var failures = new List<string>();
            Require(actual == SelfTestFail || actual == SelfTestCritical,
                $"case {oneBasedTest} status {actual} is not a failure", failures);
            Require(ReadByteFromSram(InSelfTest) != 0,
                "firmware did not retain the interactive failure screen", failures);
            Require(ReadDoubleWordFromSram(SelfTestWait) != 0,
                "firmware did not wait for failure acknowledgement", failures);
            ThrowIfAny("self-test negative control", failures);
            return $"ZS407_TWIN_SELFTEST_FAILURE=PASS case={oneBasedTest} status={actual}";
        }

        public string ReportSelfTestCase(int oneBasedTest)
        {
            if(oneBasedTest < 1 || oneBasedTest > SelfTestCount)
            {
                throw new RecoverableException("ZS407 twin self-test report case is invalid");
            }
            var status = ReadDoubleWordFromSram(SelfTestStatus
                + (ulong)((oneBasedTest - 1) * sizeof(uint)));
            var causeAddress = ReadDoubleWordFromSram(SelfTestFailCause
                + (ulong)((oneBasedTest - 1) * sizeof(uint)));
            var points = ReadWordFromSram(Setting + SettingSweepPoints);
            if(points == 0 || points > MaximumSweepPoints)
            {
                throw new RecoverableException($"ZS407 twin self-test points {points} outside 1..{MaximumSweepPoints}");
            }
            var measuredPeak = float.MinValue;
            var measuredMinimum = float.MaxValue;
            var measuredPeakIndex = 0;
            var finiteCount = 0;
            var populatedCount = 0;
            var mean = 0.0;
            var sumSquaredDifferences = 0.0;
            for(var index = 0; index < points; index++)
            {
                var value = ReadFloatFromSram(Measured + (ulong)(index * sizeof(float)));
                if(float.IsNaN(value) || float.IsInfinity(value))
                {
                    continue;
                }
                finiteCount++;
                if(Math.Abs(value) > 0.000001f)
                {
                    populatedCount++;
                }
                var difference = value - mean;
                mean += difference / finiteCount;
                sumSquaredDifferences += difference * (value - mean);
                if(value > measuredPeak)
                {
                    measuredPeak = value;
                    measuredPeakIndex = index;
                }
                if(value < measuredMinimum)
                {
                    measuredMinimum = value;
                }
            }
            if(finiteCount == 0)
            {
                measuredPeak = float.NaN;
                measuredMinimum = float.NaN;
            }
            var left = measuredPeakIndex;
            var right = measuredPeakIndex;
            while(finiteCount > 0 && left > 0 && ReadFloatFromSram(Measured
                + (ulong)(left * sizeof(float))) >= measuredPeak - 15.0f)
            {
                left--;
            }
            while(finiteCount > 0 && right < points - 1 && ReadFloatFromSram(Measured
                + (ulong)(right * sizeof(float))) >= measuredPeak - 15.0f)
            {
                right++;
            }
            var standardDeviation = finiteCount == 0
                ? double.NaN : Math.Sqrt(sumSquaredDifferences / finiteCount);
            var dynamicRange = finiteCount == 0
                ? double.NaN : measuredPeak - measuredMinimum;
            return $"ZS407_TWIN_SELFTEST_STATUS case={oneBasedTest} status={status} "
                + $"peak_dbm={ReadFloatFromSram(PeakLevel):F2} "
                + $"peak_hz={ReadQuadWordFromSram(PeakFrequency)} "
                + $"peak_index={ReadDoubleWordFromSram(PeakIndex)} "
                + $"points={points} "
                + $"cause={ReadCString(causeAddress, 32)} "
                + $"measured_peak={measuredPeak:F2}@{measuredPeakIndex} width15={right - left} "
                + $"measured_min={measuredMinimum:F2} measured_max={measuredPeak:F2} "
                + $"dynamic_range_db={dynamicRange:F2} mean={mean:F2} stddev={standardDeviation:F2} "
                + $"populated={populatedCount} finite={finiteCount} "
                + $"samples={Get<ulong>(receiver, "RssiSampleCount")} "
                + $"raw={Get<byte>(receiver, "MinimumRssiRaw")}..{Get<byte>(receiver, "PeakRssiRaw")} "
                + $"fixture={Get<int>(receiver, "SelfTestFixture")} "
                + $"cal={(Get<bool>(receiver, "CalibrationOutputEnabled") ? 1 : 0)}@{Get<double>(receiver, "CalibrationFrequencyHz"):F0} "
                + $"tuned_hz={Get<double>(receiver, "MinimumTunedInputFrequencyHz"):F0}..{Get<double>(receiver, "MaximumTunedInputFrequencyHz"):F0} "
                + $"lo_hz={Get<double>(receiver, "MinimumLocalOscillatorFrequencyHz"):F0}..{Get<double>(receiver, "MaximumLocalOscillatorFrequencyHz"):F0} "
                + $"frame=0x{Get<ulong>(display, "FramebufferHash"):X16} nonblack={Get<uint>(display, "NonBlackPixels")}";
        }

        public string Report()
        {
            return $"ZS407_TWIN_STATUS spi={Get<ulong>(fabric, "BusTransfers")} pixels={Get<ulong>(display, "PixelWrites")} "
                + $"nonblack={Get<uint>(display, "NonBlackPixels")} frame=0x{Get<ulong>(display, "FramebufferHash"):X16} "
                + $"si4468_commands={Get<ulong>(receiver, "CommandCount")} si4468_state=0x{Get<byte>(receiver, "State"):X2} "
                + $"rssi={Get<byte>(receiver, "MinimumRssiRaw")}..{Get<byte>(receiver, "PeakRssiRaw")} "
                + $"max2871_hz={Get<double>(synthesizer, "FrequencyHz"):F0} attenuation_db={Get<double>(attenuator, "AttenuationDb"):F1}";
        }

        public string ReportShell()
        {
            var bytes = new List<byte>();
            for(ulong index = 0; index < ShellLineSize; index++)
            {
                var value = ReadByteFromSram(ShellLine + index);
                if(value == 0)
                {
                    break;
                }
                bytes.Add(value);
            }
            var line = System.Text.Encoding.ASCII.GetString(bytes.ToArray())
                .Replace("\r", "\\r").Replace("\n", "\\n");
            return $"ZS407_TWIN_SHELL line={line} nargs={ReadWordFromSram(ShellNargs)} "
                + $"function=0x{ReadDoubleWordFromSram(ShellFunction):X8} "
                + $"stream=0x{ReadDoubleWordFromSram(ShellStream):X8}";
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

        private static ulong GetProfileAddress(IDictionary<string, ulong> values,
            string key, bool allowCcm = false)
        {
            ulong value;
            if(!values.TryGetValue(key, out value))
            {
                throw new RecoverableException($"ZS407 twin symbol profile is missing: {key}");
            }
            var inSram = value >= SramStart && value < SramEnd;
            var inCcm = allowCcm && value >= CcmStart && value < CcmEnd;
            if(!inSram && !inCcm)
            {
                throw new RecoverableException($"ZS407 twin symbol {key}=0x{value:X8} is outside modeled RAM");
            }
            return value;
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

        private float ReadFloatFromSram(ulong address)
        {
            return BitConverter.ToSingle(BitConverter.GetBytes(
                ReadDoubleWordFromSram(address)), 0);
        }

        private string ReadCString(ulong address, int maximumLength)
        {
            var bytes = new List<byte>();
            if(address == 0)
            {
                return string.Empty;
            }
            for(var index = 0; index < maximumLength; index++)
            {
                var value = machine.GetSystemBus(this).ReadByte(address + (ulong)index, this);
                if(value == 0)
                {
                    break;
                }
                bytes.Add(value);
            }
            return System.Text.Encoding.ASCII.GetString(bytes.ToArray());
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
        private string symbolProfileName = "v0.2.0-default";

        private ulong ChibiOsCurrentThread = 0x20001698;
        private ulong LastTouchX = 0x200071F6;
        private ulong LastTouchY = 0x200071F8;
        private ulong UiMode = 0x200072E1;
        private ulong Setting = 0x20004CE0;
        private ulong SweepMode = 0x20001400;
        private ulong InSelfTest = 0x20002861;
        private ulong SelfTestStatus = 0x20005420;
        private ulong SelfTestFailCause = 0x20005384;
        private ulong SelfTestWait = 0x200054A8;
        private ulong PeakFrequency = 0x20004508;
        private ulong PeakLevel = 0x20004514;
        private ulong PeakIndex = 0x20004510;
        private ulong ShellFunction = 0x20005324;
        private ulong ShellLine = 0x20005328;
        private ulong ShellNargs = 0x20005358;
        private ulong ShellStream = 0x2000535C;
        private ulong Measured = 0x2000289C;
        private ulong ActualRbwX10 = 0x200020EC;
        private ulong Dirty = 0x20001330;
        private ulong ScanDirty = 0x200013E4;
        private ulong Completed = 0x200022DC;
        private ulong SweepCounter = 0x20005378;
        private ulong AvoidSetting = 0x200022BC;
        private ulong FrequencyStart = 0x20002840;
        private ulong FrequencyStop = 0x20002848;
        private ulong FrequencyCount = 0x2000208E;
        private ulong FrequencyDelta = 0x20002090;
        private ulong FrequencyError = 0x20002098;
        private ulong FrequencyStartInternal = 0x200020A0;
        private ulong FrequencyCache = 0x10000000;
        private static readonly string[] SymbolProfileKeys =
        {
            "chibios_current_thread", "last_touch_x", "last_touch_y", "ui_mode",
            "setting", "sweep_mode", "in_selftest", "selftest_status",
            "selftest_fail_cause", "selftest_wait", "peak_frequency", "peak_level",
            "peak_index", "shell_function", "shell_line", "shell_nargs", "shell_stream",
            "measured", "actual_rbw_x10", "dirty", "scan_dirty", "completed",
            "sweep_counter", "avoid_setting", "frequency_start", "frequency_stop",
            "frequency_count", "frequency_delta", "frequency_error",
            "frequency_start_internal", "frequency_cache"
        };
        private const ulong SramStart = 0x20000000;
        private const ulong SramEnd = 0x20010000;
        private const ulong CcmStart = 0x10000000;
        private const ulong CcmEnd = 0x10002000;
        private const ulong SettingAutoAttenuation = 5;
        private const ulong SettingTest = 442;
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
        private const ulong SettingTestArgument = 1568;
        private const long MaximumAnalyzerFrequencyHz = 17922600000L;
        private const int MinimumSweepPoints = 20;
        private const int MaximumSweepPoints = 450;
        private const int MaximumRbwX10 = 8500;
        private const int MaximumAttenuationX2 = 62;
        private const byte AnalyzerLowMode = 0;
        private const byte GeneratorLowMode = 2;
        private const byte SweepEnabled = 0x01;
        private const byte SweepSelfTest = 0x08;
        private const int SelfTestCount = 14;
        private const int SelfTestWaiting = 0;
        private const int SelfTestPass = 1;
        private const int SelfTestFail = 2;
        private const int SelfTestCritical = 3;
        private const int ShellLineSize = 48;
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
