/* Hardware-free reproducer for tinySA chprintf.c::etoa(). */
#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define OUTPUT_CAPACITY 32

static void render(float input, bool fixed, char output[OUTPUT_CAPACITY])
{
  char *p = output;
  float num = input;
  int exponent = 0;

  if (num < 0.0f) {
    *p++ = '-';
    num = -num;
  }
  if (num == 0.0f) {
    *p++ = '0';
    *p = '\0';
    return;
  }

  while (num < 10.0f) {
    num *= 10.0f;
    exponent--;
  }
  while (fixed ? num >= 10.0f : num > 10.0f) {
    num /= 10.0f;
    exponent++;
  }

  *p++ = (char)(((int)num) + '0');
  num *= 10.0f;
  *p++ = '.';
  for (int precision = 0; precision < 6; precision++) {
    *p++ = (char)((((int)num) % 10) + '0');
    num *= 10.0f;
  }
  *p++ = 'e';
  if (exponent < 0) {
    *p++ = '-';
    exponent = -exponent;
  } else {
    *p++ = '+';
  }
  *p++ = (char)((exponent / 10) + '0');
  *p++ = (char)((exponent % 10) + '0');
  *p = '\0';
}

static bool valid_scientific(const char *text)
{
  if (*text == '-')
    text++;
  if (text[0] < '0' || text[0] > '9' || text[1] != '.')
    return false;
  for (int i = 2; i < 8; i++) {
    if (text[i] < '0' || text[i] > '9')
      return false;
  }
  return text[8] == 'e' && (text[9] == '+' || text[9] == '-') &&
         text[10] >= '0' && text[10] <= '9' &&
         text[11] >= '0' && text[11] <= '9' && text[12] == '\0';
}

static int check_exact(float value, const char *expected)
{
  char legacy[OUTPUT_CAPACITY];
  char fixed[OUTPUT_CAPACITY];
  render(value, false, legacy);
  render(value, true, fixed);
  if (strchr(legacy, ':') == NULL || strcmp(fixed, expected) != 0) {
    fprintf(stderr, "exact %.9g: legacy=%s fixed=%s expected=%s\n",
            (double)value, legacy, fixed, expected);
    return 1;
  }
  return 0;
}

static int check_boundary(float value)
{
  char fixed[OUTPUT_CAPACITY];
  char *end = NULL;
  render(value, true, fixed);
  if (!valid_scientific(fixed)) {
    fprintf(stderr, "boundary %.9g is not numeric: %s\n",
            (double)value, fixed);
    return 1;
  }
  errno = 0;
  float parsed = strtof(fixed, &end);
  float tolerance = fmaxf(fabsf(value) * 2.0e-6f, 1.0e-7f);
  if (errno != 0 || end == NULL || *end != '\0' ||
      fabsf(parsed - value) > tolerance) {
    fprintf(stderr, "boundary %.9g round-trip failed: %s -> %.9g\n",
            (double)value, fixed, (double)parsed);
    return 1;
  }
  return 0;
}

int main(void)
{
  static const struct {
    float value;
    const char *expected;
  } exact[] = {
    {1.0f, "1.000000e+00"}, {-1.0f, "-1.000000e+00"},
    {10.0f, "1.000000e+01"}, {-10.0f, "-1.000000e+01"},
    {100.0f, "1.000000e+02"}, {-100.0f, "-1.000000e+02"},
    {1000.0f, "1.000000e+03"}, {-1000.0f, "-1.000000e+03"},
  };
  static const float powers[] = {1.0f, 10.0f, 100.0f, 1000.0f};
  char legacy_example[OUTPUT_CAPACITY];
  char fixed_example[OUTPUT_CAPACITY];
  int failures = 0;
  int boundary_count = 0;

  for (size_t i = 0; i < sizeof(exact) / sizeof(exact[0]); i++)
    failures += check_exact(exact[i].value, exact[i].expected);

  for (size_t i = 0; i < sizeof(powers) / sizeof(powers[0]); i++) {
    float neighbors[] = {
      nextafterf(powers[i], 0.0f),
      nextafterf(powers[i], INFINITY),
    };
    for (size_t j = 0; j < sizeof(neighbors) / sizeof(neighbors[0]); j++) {
      failures += check_boundary(neighbors[j]);
      failures += check_boundary(-neighbors[j]);
      boundary_count += 2;
    }
  }

  if (failures != 0)
    return 1;
  render(-100.0f, false, legacy_example);
  render(-100.0f, true, fixed_example);
  printf("etoa_power_boundary=PASS legacy_minus_100=%s fixed_minus_100=%s "
         "exact=%zu boundaries=%d\n",
         legacy_example, fixed_example,
         sizeof(exact) / sizeof(exact[0]), boundary_count);
  return 0;
}
