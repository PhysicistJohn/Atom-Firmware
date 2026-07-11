// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// Shared ADC12 register block. The ZS407 firmware only programs CCR, but
    /// keeping the value readable is important because the STM32 HAL uses
    /// read/modify/write accesses here.
    /// </summary>
    public sealed class STM32F303AdcCommon : IDoubleWordPeripheral, IKnownSize
    {
        public long Size => 0x10;

        public void Reset()
        {
            commonControl = 0;
        }

        public uint ReadDoubleWord(long offset)
        {
            return offset == CommonControl ? commonControl : 0;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == CommonControl)
            {
                commonControl = value;
            }
        }

        private uint commonControl;
        private const long CommonControl = 0x08;
    }

    /// <summary>
    /// STM32F303 ADC model with deterministic channel values and DMA requests.
    /// </summary>
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public sealed class STM32F303Adc : IDoubleWordPeripheral, IKnownSize
    {
        public STM32F303Adc(IMachine machine, STM32F303Dma dma,
            int dmaChannel, int unit)
        {
            this.machine = machine;
            this.dma = dma ?? throw new ArgumentNullException(nameof(dma));
            this.dmaChannel = dmaChannel;
            this.unit = unit;
            channelValues = new uint[19];
            Reset();
        }

        public long Size => 0x100;

        public GPIO IRQ { get; } = new GPIO();

        public bool TouchPressed => touchPressed;

        public uint TouchXRaw => touchXRaw;

        public uint TouchYRaw => touchYRaw;

        public int TouchXPixel => touchXPixel;

        public int TouchYPixel => touchYPixel;

        public void Reset()
        {
            registers.Clear();
            interruptStatus = 0;
            control = 0;
            data = 0;
            armedForExternalTrigger = false;
            conversionPending = false;
            touchProbePending = false;
            touchPressed = false;
            touchXRaw = 0;
            touchYRaw = 0;
            touchXPixel = 0;
            touchYPixel = 0;
            for(var i = 0; i < channelValues.Length; ++i)
            {
                channelValues[i] = 0;
            }

            if(unit == 1)
            {
                channelValues[1] = 2250; // ZS407 hardware ID divider.
                channelValues[17] = 2480; // Approximately 4.0 V battery.
                channelValues[18] = 1500; // Internal reference.
            }
            IRQ.Unset();
        }

        public void SetChannelValue(int channel, uint value)
        {
            if(channel < 0 || channel >= channelValues.Length)
            {
                throw new ArgumentOutOfRangeException(nameof(channel));
            }
            channelValues[channel] = value & 0xFFFu;
        }

        public void SetTouchPixel(int x, int y)
        {
            if(unit != 2)
            {
                throw new InvalidOperationException("Touch is connected to ADC2");
            }
            if(x < 0 || x >= TouchWidth || y < 0 || y >= TouchHeight)
            {
                throw new ArgumentOutOfRangeException();
            }

            touchXRaw = (uint)((x * (TouchXMaximum - TouchXMinimum)
                + 463 * TouchXMinimum - 16 * TouchXMaximum) / 447);
            touchYRaw = (uint)((y * (TouchYMaximum - TouchYMinimum)
                + 303 * TouchYMinimum - 16 * TouchYMaximum) / 287);
            touchXPixel = x;
            touchYPixel = y;
            touchPressed = true;
            if(armedForExternalTrigger)
            {
                ScheduleConversion();
            }
            ScheduleTouchProbe();
        }

        public void ReleaseTouch()
        {
            if(unit != 2)
            {
                throw new InvalidOperationException("Touch is connected to ADC2");
            }
            touchPressed = false;
        }

        public void TriggerExternalConversion()
        {
            if(armedForExternalTrigger)
            {
                ScheduleConversion();
            }
        }

        public uint ReadDoubleWord(long offset)
        {
            return offset switch
            {
                InterruptStatus => interruptStatus,
                Control => control,
                Data => data,
                _ => registers.TryGetValue(offset, out var value) ? value : 0,
            };
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case InterruptStatus:
                    interruptStatus &= ~value;
                    UpdateInterrupt();
                    break;
                case Control:
                    WriteControl(value);
                    break;
                default:
                    registers[offset] = value;
                    break;
            }
        }

        private void WriteControl(uint value)
        {
            control = value;

            // Calibration completes synchronously in the deterministic twin.
            control &= ~Calibration;

            if((value & Disable) != 0)
            {
                control &= ~(Disable | Enable | Start | Stop);
                interruptStatus &= ~Ready;
                conversionPending = false;
            }
            if((value & Stop) != 0)
            {
                control &= ~(Stop | Start);
                armedForExternalTrigger = false;
                conversionPending = false;
            }
            if((value & Enable) != 0)
            {
                control |= Enable;
                interruptStatus |= Ready;
            }
            if((value & Start) != 0)
            {
                control |= Start;
                var configuration = GetRegister(Configuration);
                if((configuration & ExternalTriggerEnableMask) != 0)
                {
                    armedForExternalTrigger = true;
                }
                else
                {
                    ScheduleConversion();
                }
            }
            UpdateInterrupt();
        }

        private void ScheduleConversion()
        {
            if(conversionPending)
            {
                return;
            }
            conversionPending = true;
            // Keep completion outside the SVC context used by ChibiOS to put
            // the calling thread to sleep. A same-instruction completion can
            // otherwise look like a nested exception to Cortex-M RETTOBASE.
            machine.ScheduleAction(TimeInterval.FromMicroseconds(50), _ => CompleteConversion(),
                name: $"ZS407 ADC{unit} conversion");
        }

        private void ScheduleTouchProbe()
        {
            if(unit != 2 || !touchPressed || touchProbePending)
            {
                return;
            }
            touchProbePending = true;
            // The panel watchdog is driven by TIM1 TRGO at 20 Hz. Keeping the
            // trigger here makes a press robust across the short interval in
            // which the firmware stops ADC2 to measure X/Y or change groups.
            machine.ScheduleAction(TimeInterval.FromMilliseconds(50), _ =>
            {
                touchProbePending = false;
                if(!touchPressed)
                {
                    return;
                }
                if(armedForExternalTrigger)
                {
                    ScheduleConversion();
                }
                ScheduleTouchProbe();
            }, name: "ZS407 touch-panel TIM1 TRGO");
        }

        private void CompleteConversion()
        {
            if(!conversionPending)
            {
                return;
            }
            conversionPending = false;
            var sequence = BuildSequence();
            var index = 0;
            Func<uint> provider = () =>
            {
                var channel = sequence[index % sequence.Length];
                index++;
                data = GetChannelSample(channel);
                return data;
            };

            if(dma.IsEnabled(dmaChannel))
            {
                dma.CompletePeripheralToMemory(dmaChannel, provider);
            }
            else
            {
                provider();
            }

            interruptStatus |= EndOfConversion | EndOfSequence;
            var configuration = GetRegister(Configuration);
            var externallyTriggered = (configuration & ExternalTriggerEnableMask) != 0;
            if(externallyTriggered)
            {
                var threshold = GetRegister(Threshold1);
                var low = threshold & 0xFFFu;
                var high = (threshold >> 16) & 0xFFFu;
                if(data < low || data > high)
                {
                    interruptStatus |= AnalogWatchdog1;
                }
                armedForExternalTrigger = true;
            }
            else
            {
                control &= ~Start;
                armedForExternalTrigger = false;
            }
            UpdateInterrupt();
        }

        private uint GetChannelSample(int channel)
        {
            if(unit != 2 || !touchPressed)
            {
                return channelValues[channel];
            }
            if(channel == TouchXChannel)
            {
                return touchXRaw;
            }
            if(channel == TouchYChannel)
            {
                // PB0 is high for touch-presence sensing and low while Y is
                // measured. This mirrors the four-wire electrode sequence.
                var gpioBOutput = machine.GetSystemBus(this)
                    .ReadDoubleWord(GpioBOutputData, this);
                return (gpioBOutput & 1u) != 0 ? TouchSenseLevel : touchYRaw;
            }
            return channelValues[channel];
        }

        private int[] BuildSequence()
        {
            var sqr1 = GetRegister(Sequence1);
            var count = (int)(sqr1 & 0xFu) + 1;
            var sequence = new int[Math.Max(1, count)];
            for(var rank = 0; rank < sequence.Length; ++rank)
            {
                sequence[rank] = rank switch
                {
                    0 => (int)((sqr1 >> 6) & 0x1Fu),
                    1 => (int)((sqr1 >> 12) & 0x1Fu),
                    2 => (int)((sqr1 >> 18) & 0x1Fu),
                    3 => (int)((sqr1 >> 24) & 0x1Fu),
                    _ => 0,
                };
                if(sequence[rank] >= channelValues.Length)
                {
                    sequence[rank] = 0;
                }
            }
            return sequence;
        }

        private uint GetRegister(long offset)
        {
            return registers.TryGetValue(offset, out var value) ? value : 0;
        }

        private void UpdateInterrupt()
        {
            var enabled = GetRegister(InterruptEnable);
            IRQ.Set((interruptStatus & enabled &
                (Overrun | AnalogWatchdog1)) != 0);
        }

        private readonly STM32F303Dma dma;
        private readonly IMachine machine;
        private readonly int dmaChannel;
        private readonly int unit;
        private readonly uint[] channelValues;
        private readonly Dictionary<long, uint> registers = new Dictionary<long, uint>();

        private uint interruptStatus;
        private uint control;
        private uint data;
        private bool armedForExternalTrigger;
        private bool conversionPending;
        private bool touchProbePending;
        private bool touchPressed;
        private uint touchXRaw;
        private uint touchYRaw;
        private int touchXPixel;
        private int touchYPixel;

        private const uint Ready = 1u << 0;
        private const uint EndOfConversion = 1u << 2;
        private const uint EndOfSequence = 1u << 3;
        private const uint Overrun = 1u << 4;
        private const uint AnalogWatchdog1 = 1u << 7;
        private const uint Enable = 1u << 0;
        private const uint Disable = 1u << 1;
        private const uint Start = 1u << 2;
        private const uint Stop = 1u << 4;
        private const uint Calibration = 1u << 31;
        private const uint ExternalTriggerEnableMask = 3u << 10;
        private const uint TouchSenseLevel = 3000;
        private const int TouchXChannel = 3;
        private const int TouchYChannel = 4;
        private const int TouchWidth = 480;
        private const int TouchHeight = 320;
        private const int TouchXMinimum = 444;
        private const int TouchXMaximum = 3552;
        private const int TouchYMinimum = 715;
        private const int TouchYMaximum = 3499;
        private const ulong GpioBOutputData = 0x48000414;

        private const long InterruptStatus = 0x00;
        private const long InterruptEnable = 0x04;
        private const long Control = 0x08;
        private const long Configuration = 0x0C;
        private const long Threshold1 = 0x20;
        private const long Sequence1 = 0x30;
        private const long Data = 0x40;
    }
}
