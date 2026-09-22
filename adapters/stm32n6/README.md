# STM32N6 adapter

Select `stm32n6.clayer.yml` and `stm32n6_tim2.clayer.yml` with the common layer.
Requires a secure privileged M55 build (`-mcmse`), the ST device define, CMSIS
headers and HAL RCC/RCCEx modules.

- Reserves all of TIM2 and `TIM2_IRQHandler`; do not initialize it through Cube/HAL
  or use its PWM, DMA or capture channels. Application SysTick/HAL ticks stay unchanged.
- Uses update interrupts, PSC=0, ARR=period-1. The clock comes from
  `HAL_RCCEx_GetTIMGFreq()`, including TIMPRE.
- TIM2 and its IRQ must be Secure and accessible. First init rejects an enabled
  clock or NVIC IRQ. Stop disables sampling but retains the timer reservation.

Stack bounds default to `DTCM_BASE_S` with size read once from `MEMSYSCTL->DTCMCR`.
Disabled, absent or invalid DTCM fails initialization. Startup must initialize the
actual FlexRAM allocation; the DFP memory map alone does not establish it.
Explicit stack bounds bypass detection. The capture buffer uses ordinary aligned BSS.

See [configuration](../../docs/CONFIGURATION.md) for memory overrides.
GCC/AC6 compile-checked against ST headers; STM32N6 hardware execution is unverified.
