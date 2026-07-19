# RC5 ChibiOS lineage recovery

The exact `v0.4-chibios21.11.5-rc5` firmware uses ChibiOS commit
`b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9`. That commit consists of two
local commits on top of the public `ver21.11.5` tag:

1. `2b8f425d26a61a7887916f7052b401f9e767a949` restores the STM32F0 TIM14 GPT
   ISR.
2. `b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9` preserves USBv1 endpoint-zero
   PMA allocation across reconfiguration.

The public base is `f4bbadf964fc746aef8bbcf34135c7d8fabb8eae`, available as tag
`ver21.11.5` from `https://github.com/ChibiOS/ChibiOS.git`. The two local
commits are preserved in `tinysa-chibios-21.11.5-rc5.bundle`; the bundle is
thin and therefore requires that public base object.

Verify the tracked bundle before importing it:

```sh
cd /path/to/Atom-Firmware
shasum -a 256 -c release-manifests/tinysa-chibios-21.11.5-rc5.bundle.sha256
git -C ChibiOS fetch --tags https://github.com/ChibiOS/ChibiOS.git ver21.11.5
git -C ChibiOS bundle verify "$PWD/release-manifests/tinysa-chibios-21.11.5-rc5.bundle"
```

Recover the exact RC5 ChibiOS branch without changing the checked-out
submodule worktree:

```sh
git -C ChibiOS fetch --no-tags --no-write-fetch-head \
  "$PWD/release-manifests/tinysa-chibios-21.11.5-rc5.bundle" \
  refs/heads/physicistjohn/tinysa-21.11.5-rc5:refs/heads/physicistjohn/tinysa-21.11.5-rc5
test "$(git -C ChibiOS rev-parse refs/heads/physicistjohn/tinysa-21.11.5-rc5)" = \
  b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9
```

The matching superproject release branch is
`physicistjohn/release-v0.4-chibios21.11.5-rc5` at
`6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2`; its `ChibiOS` gitlink must
resolve to the exact commit above. That branch is independently preserved in
`tinysa-firmware-v0.4-chibios21.11.5-rc5.bundle`, based on shared ancestor
`0b0cd3c85420e5255bb942c7e8b25d648c9d214a`:

```sh
shasum -a 256 -c release-manifests/tinysa-firmware-v0.4-chibios21.11.5-rc5.bundle.sha256
git bundle verify release-manifests/tinysa-firmware-v0.4-chibios21.11.5-rc5.bundle
git fetch --no-tags --no-write-fetch-head --recurse-submodules=no \
  release-manifests/tinysa-firmware-v0.4-chibios21.11.5-rc5.bundle \
  refs/heads/physicistjohn/release-v0.4-chibios21.11.5-rc5:refs/heads/physicistjohn/release-v0.4-chibios21.11.5-rc5
test "$(git rev-parse refs/heads/physicistjohn/release-v0.4-chibios21.11.5-rc5)" = \
  6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2
test "$(git ls-tree 6fdf6f307ecb0cef2e3af478b0fc7b80a1fd13e2 ChibiOS | awk '{print $3}')" = \
  b3f82b396de7cf2a9e85bc8f1575fbd58e9428d9
```

Do not substitute the abandoned pre-amend seal `6eaf515`.

The mailbox patches under `upstream-patches/chibios/` remain the human-review
and vendor-submission form. This bundle exists specifically to preserve the
exact build lineage until both commits are hosted by a durable ChibiOS fork.
