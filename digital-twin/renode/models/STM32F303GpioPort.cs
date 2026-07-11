// SPDX-License-Identifier: MIT

using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.GPIOPort;

namespace Antmicro.Renode.Peripherals.ZS407
{
    /// <summary>
    /// STM32F303 GPIO port with independent input and output state.
    ///
    /// Renode 1.16.1's generic STM32 GPIO model stores IDR and ODR in one
    /// state array. That makes an ODR reset value drive pins configured as
    /// inputs and, on the ZS407, leaves all three active-high jog contacts
    /// asserted even though their PUPDR fields select pull-downs.
    /// </summary>
    [AllowedTranslations(AllowedTranslation.WordToDoubleWord)]
    public sealed class STM32F303GpioPort : BaseGPIOPort,
        IDoubleWordPeripheral, ILocalGPIOReceiver, IKnownSize
    {
        public STM32F303GpioPort(IMachine machine, uint modeResetValue = 0,
            uint outputSpeedResetValue = 0,
            uint pullUpPullDownResetValue = 0,
            uint numberOfAFs = 16) : base(machine, NumberOfPins)
        {
            if(numberOfAFs == 0 || numberOfAFs > 16)
            {
                throw new ArgumentOutOfRangeException(nameof(numberOfAFs));
            }

            this.modeResetValue = modeResetValue;
            this.outputSpeedResetValue = outputSpeedResetValue;
            this.pullUpPullDownResetValue = pullUpPullDownResetValue;
            this.numberOfAFs = numberOfAFs;
            alternateFunctionReceivers = new AlternateFunctionReceiver[NumberOfPins];
            for(var pin = 0; pin < NumberOfPins; ++pin)
            {
                alternateFunctionReceivers[pin] = new AlternateFunctionReceiver(this, pin);
            }
            Reset();
        }

        public long Size => 0x400;

        public override void Reset()
        {
            base.Reset();
            mode = modeResetValue;
            outputType = 0;
            outputSpeed = outputSpeedResetValue;
            pullUpPullDown = pullUpPullDownResetValue;
            outputData = 0;
            configurationLock = 0;
            alternateFunctionLow = 0;
            alternateFunctionHigh = 0;
            Array.Clear(externallyDriven, 0, externallyDriven.Length);
            for(var pin = 0; pin < NumberOfPins; ++pin)
            {
                alternateFunctionReceivers[pin].Reset();
            }
            RefreshOutputs();
        }

        public override void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= NumberOfPins)
            {
                throw new ArgumentOutOfRangeException(nameof(number));
            }

            externallyDriven[number] = true;
            State[number] = value;
            // EXTI is connected to the port output in the platform graph.
            if(GetMode(number) == PinMode.Input)
            {
                Connections[number].Set(value);
            }
        }

        public IGPIOReceiver GetLocalReceiver(int pin)
        {
            if(pin < 0 || pin >= NumberOfPins)
            {
                throw new ArgumentOutOfRangeException(nameof(pin));
            }
            return alternateFunctionReceivers[pin];
        }

        public uint ReadDoubleWord(long offset)
        {
            return offset switch
            {
                Mode => mode,
                OutputType => outputType,
                OutputSpeed => outputSpeed,
                PullUpPullDown => pullUpPullDown,
                InputData => ReadInputData(),
                OutputData => outputData,
                ConfigurationLock => configurationLock,
                AlternateFunctionLow => alternateFunctionLow,
                AlternateFunctionHigh => alternateFunctionHigh,
                _ => 0,
            };
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case Mode:
                    mode = value;
                    RefreshOutputs();
                    break;
                case OutputType:
                    outputType = value & 0xFFFFu;
                    break;
                case OutputSpeed:
                    outputSpeed = value;
                    break;
                case PullUpPullDown:
                    pullUpPullDown = value;
                    break;
                case OutputData:
                    outputData = value & 0xFFFFu;
                    RefreshOutputs();
                    break;
                case BitSetReset:
                    outputData &= ~((value >> 16) & 0xFFFFu);
                    // STM32 BSRR set bits win when both halves select a pin.
                    outputData |= value & 0xFFFFu;
                    RefreshOutputs();
                    break;
                case ConfigurationLock:
                    configurationLock = value & 0x1FFFFu;
                    break;
                case AlternateFunctionLow:
                    alternateFunctionLow = value;
                    RefreshOutputs();
                    break;
                case AlternateFunctionHigh:
                    alternateFunctionHigh = value;
                    RefreshOutputs();
                    break;
                case BitReset:
                    outputData &= ~(value & 0xFFFFu);
                    RefreshOutputs();
                    break;
            }
        }

        private uint ReadInputData()
        {
            var result = 0u;
            for(var pin = 0; pin < NumberOfPins; ++pin)
            {
                var pinMode = GetMode(pin);
                var value = pinMode == PinMode.Output
                    ? GetOutputBit(pin)
                    : externallyDriven[pin]
                        ? State[pin]
                        : GetPull(pin) == Pull.Up;
                if(value)
                {
                    result |= 1u << pin;
                }
            }
            return result;
        }

        private void RefreshOutputs()
        {
            for(var pin = 0; pin < NumberOfPins; ++pin)
            {
                if(GetMode(pin) == PinMode.Output)
                {
                    Connections[pin].Set(GetOutputBit(pin));
                }
            }
        }

        private void SetAlternateFunctionOutput(int pin, int function,
            bool value)
        {
            if(GetMode(pin) != PinMode.AlternateFunction
                || function != GetAlternateFunction(pin))
            {
                return;
            }
            Connections[pin].Set(value);
        }

        private PinMode GetMode(int pin)
        {
            return (PinMode)((mode >> (pin * 2)) & 0x3u);
        }

        private Pull GetPull(int pin)
        {
            return (Pull)((pullUpPullDown >> (pin * 2)) & 0x3u);
        }

        private bool GetOutputBit(int pin)
        {
            return (outputData & (1u << pin)) != 0;
        }

        private int GetAlternateFunction(int pin)
        {
            var register = pin < 8 ? alternateFunctionLow : alternateFunctionHigh;
            return (int)((register >> ((pin & 7) * 4)) & 0xFu);
        }

        private sealed class AlternateFunctionReceiver : IGPIOReceiver
        {
            public AlternateFunctionReceiver(STM32F303GpioPort parent, int pin)
            {
                this.parent = parent;
                this.pin = pin;
            }

            public void Reset()
            {
            }

            public void OnGPIO(int number, bool value)
            {
                if(number < 0 || number >= parent.numberOfAFs)
                {
                    return;
                }
                parent.SetAlternateFunctionOutput(pin, number, value);
            }

            private readonly STM32F303GpioPort parent;
            private readonly int pin;
        }

        private readonly bool[] externallyDriven = new bool[NumberOfPins];
        private readonly AlternateFunctionReceiver[] alternateFunctionReceivers;
        private readonly uint modeResetValue;
        private readonly uint outputSpeedResetValue;
        private readonly uint pullUpPullDownResetValue;
        private readonly uint numberOfAFs;

        private uint mode;
        private uint outputType;
        private uint outputSpeed;
        private uint pullUpPullDown;
        private uint outputData;
        private uint configurationLock;
        private uint alternateFunctionLow;
        private uint alternateFunctionHigh;

        private const int NumberOfPins = 16;
        private const long Mode = 0x00;
        private const long OutputType = 0x04;
        private const long OutputSpeed = 0x08;
        private const long PullUpPullDown = 0x0C;
        private const long InputData = 0x10;
        private const long OutputData = 0x14;
        private const long BitSetReset = 0x18;
        private const long ConfigurationLock = 0x1C;
        private const long AlternateFunctionLow = 0x20;
        private const long AlternateFunctionHigh = 0x24;
        private const long BitReset = 0x28;

        private enum PinMode : uint
        {
            Input = 0,
            Output = 1,
            AlternateFunction = 2,
            Analog = 3,
        }

        private enum Pull : uint
        {
            None = 0,
            Up = 1,
            Down = 2,
            Reserved = 3,
        }
    }
}
