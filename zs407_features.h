#ifndef ZS407_FEATURES_H
#define ZS407_FEATURES_H

/*
 * The official/reproduction build does not define ZS407_PHASE_BUILD and keeps
 * the upstream behavior byte-for-byte. Phase images opt into cumulative
 * modernization behavior through Makefile PHASE=N.
 */
#ifndef ZS407_PHASE_BUILD
#define ZS407_PHASE_BUILD 0
#endif

#ifndef ZS407_PHASE
#define ZS407_PHASE (-1)
#endif

#if ZS407_PHASE_BUILD
#define ZS407_FEATURE_SAFE_TIMING 1
#define ZS407_FLASH_WAIT_STATES 1U
#define ZS407_LCD_SPI_HZ 12000000U
#define ZS407_SI4468_SPI_HZ 6000000U
#define ZS407_MAX2871_SPI_HZ 12000000U
#define ZS407_PE4302_SPI_HZ 6000000U
#else
#define ZS407_FEATURE_SAFE_TIMING 0
#define ZS407_FLASH_WAIT_STATES 0U
#define ZS407_LCD_SPI_HZ 24000000U
#define ZS407_SI4468_SPI_HZ 12000000U
#define ZS407_MAX2871_SPI_HZ 24000000U
#define ZS407_PE4302_SPI_HZ 6000000U
#endif

#endif /* ZS407_FEATURES_H */
