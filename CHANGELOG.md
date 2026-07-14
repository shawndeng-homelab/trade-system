# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## [0.8.0](https://github.com/shawndeng-homelab/trade-system/compare/93716d64265f6012ebafe4c5a5e3bb94b1b78a03..0.8.0) - 2026-07-14
### Package updates
- [trade-system-strategies-0.4.0](packages/trade-system-strategies) bumped to [trade-system-strategies-0.4.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-strategies-0.3.0..trade-system-strategies-0.4.0)
- [trade-system-core-0.2.0](packages/trade-system-core) bumped to [trade-system-core-0.2.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-core-0.1.1..trade-system-core-0.2.0)
- [trade-system-massive-0.2.0](packages/trade-system-massive) bumped to [trade-system-massive-0.2.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-massive-0.1.1..trade-system-massive-0.2.0)
### Global changes
#### Bug Fixes
- **(ci)** only publish packages with new version tags - ([fe70f87](https://github.com/shawndeng-homelab/trade-system/commit/fe70f87acc8529ec5cf758f06b14dc3d99fb8733)) - ShawnDeng-code
- **(massive)** normalize integer volumes to precision=0 - ([e785e89](https://github.com/shawndeng-homelab/trade-system/commit/e785e8920fc7c2fb6f7620279a8fc864120444fa)) - ShawnDeng-code
#### Features
- **(core)** support option instruments in backtest data pipeline - ([6b36098](https://github.com/shawndeng-homelab/trade-system/commit/6b36098ff7e1b033ffc17a2a35507efad84681c6)) - ShawnDeng-code
- **(massive,strategies)** add option catalog loader + native BS greeks integration - ([ac2f4fa](https://github.com/shawndeng-homelab/trade-system/commit/ac2f4fa644e7b0065a2198e71119d54f07b4f970)) - ShawnDeng-code
- **(strategies)** implement PMCC strategy lifecycle - ([bdb51b3](https://github.com/shawndeng-homelab/trade-system/commit/bdb51b35ac40fb41099fa0564a8cda2c06da4ec2)) - ShawnDeng-code
#### Refactoring
- **(core)** remove grid/quick_backtest, use NAUTILUS_PATH for data catalog - ([93716d6](https://github.com/shawndeng-homelab/trade-system/commit/93716d64265f6012ebafe4c5a5e3bb94b1b78a03)) - ShawnDeng-code

- - -

## [0.7.0](https://github.com/shawndeng-homelab/trade-system/compare/5d5aff68c15212709e74e087ded9d4463fe61002..0.7.0) - 2026-07-06
### Package updates
- [trade-system-core](packages/trade-system-core) bumped to [trade-system-core-0.1.0](https://github.com/shawndeng-homelab/trade-system/compare/98859a9af066acb7867d3eba6e4dba167c5725af..trade-system-core-0.1.0)
- [trade-system-strategies-0.3.0](packages/trade-system-strategies) bumped to [trade-system-strategies-0.3.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-strategies-0.2.0..trade-system-strategies-0.3.0)
### Global changes
#### Bug Fixes
- use SPY.ARCX instrument id to match catalog data - ([587e95b](https://github.com/shawndeng-homelab/trade-system/commit/587e95bb87ba8819a5b87f4abd451942ce480730)) - ShawnDeng-code
#### Features
- **(core)** add unified runner for backtest, live trading, and parameter optimisation - ([5099428](https://github.com/shawndeng-homelab/trade-system/commit/5099428fbc8c0dc260a6c186d9900416a2dd8d80)) - ShawnDeng-code
- **(core)** default HTML reports to .tmp dir, support configurable output_dir - ([072afa6](https://github.com/shawndeng-homelab/trade-system/commit/072afa639d62039e568a15cdb981ca73163ffc5c)) - ShawnDeng-code
- add 'just add-package' command for workspace package creation - ([8411d53](https://github.com/shawndeng-homelab/trade-system/commit/8411d532e3221e8d15dbdb336deb5242f149a180)) - ShawnDeng-code
- add orb strategy - ([5d5aff6](https://github.com/shawndeng-homelab/trade-system/commit/5d5aff68c15212709e74e087ded9d4463fe61002)) - ShawnDeng-code

- - -

## [0.6.0](https://github.com/shawndeng-homelab/trade-system/compare/68d10afd4620f0ccb8c0b06ec2af72d73ae30895..0.6.0) - 2026-07-04
### Package updates
- [trade-system-massive](packages/trade-system-massive) bumped to [trade-system-massive-0.1.0](https://github.com/shawndeng-homelab/trade-system/compare/98859a9af066acb7867d3eba6e4dba167c5725af..trade-system-massive-0.1.0)
### Global changes
#### Features
- **(massive)** register package in cog.toml and add SPY 1-min download script - ([83f5305](https://github.com/shawndeng-homelab/trade-system/commit/83f5305c3b3899cea09d19653cd05ca8a55756c8)) - ShawnDeng-code
- add add mmassive futures - ([68d10af](https://github.com/shawndeng-homelab/trade-system/commit/68d10afd4620f0ccb8c0b06ec2af72d73ae30895)) - ShawnDeng-code

- - -

## [0.5.0](https://github.com/shawndeng-homelab/trade-system/compare/32c3a873f444ba841079d20c4434d7a4f35107ae..0.5.0) - 2026-07-03
### Package updates
- [trade-system-venues-0.4.0](packages/trade-system-venues) bumped to [trade-system-venues-0.4.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-venues-0.3.0..trade-system-venues-0.4.0)
- [trade-system-strategies-0.2.0](packages/trade-system-strategies) bumped to [trade-system-strategies-0.2.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-strategies-0.1.1..trade-system-strategies-0.2.0)
### Global changes
#### Features
- add rsi backtesting scripts - ([9a0b822](https://github.com/shawndeng-homelab/trade-system/commit/9a0b822f9c548db2d2231121d8a503a7a14c36eb)) - ShawnDeng-code
- update massive sdk - ([32c3a87](https://github.com/shawndeng-homelab/trade-system/commit/32c3a873f444ba841079d20c4434d7a4f35107ae)) - colyerdeng

- - -

## [0.4.1](https://github.com/shawndeng-homelab/trade-system/compare/0.4.0..0.4.1) - 1970-01-01
### Package updates
- [trade-system-strategies-0.1.1](packages/trade-system-strategies) bumped to [trade-system-strategies-0.1.1](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-strategies-0.1.0..trade-system-strategies-0.1.1)
### Global changes

- - -

## [0.4.0](https://github.com/shawndeng-homelab/trade-system/compare/c66f7d81c16a4d426a51a9ddb59ea8c48b35b845..0.4.0) - 2026-07-02
### Package updates
- [trade-system-strategies](packages/trade-system-strategies) bumped to [trade-system-strategies-0.1.0](https://github.com/shawndeng-homelab/trade-system/compare/98859a9af066acb7867d3eba6e4dba167c5725af..trade-system-strategies-0.1.0)
### Global changes
#### Documentation
- **(strategies)** explain option selection & roll/close core logic - ([c66f7d8](https://github.com/shawndeng-homelab/trade-system/commit/c66f7d81c16a4d426a51a9ddb59ea8c48b35b845)) - colyerdeng
#### Features
- **(strategies)** add trade-system-strategies package skeleton - ([7bf0cbd](https://github.com/shawndeng-homelab/trade-system/commit/7bf0cbd6f91e41fe4fa9d656e76658fb3ff622ae)) - colyerdeng

- - -

## [0.3.0](https://github.com/shawndeng-homelab/trade-system/compare/c46f6586223bd49a75379a3b99759a95cd639861..0.3.0) - 2026-07-02
### Package updates
- [trade-system-venues-0.3.0](packages/trade-system-venues) bumped to [trade-system-venues-0.3.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-venues-0.2.0..trade-system-venues-0.3.0)
### Global changes
#### Miscellaneous Chores
- add scripts - ([c46f658](https://github.com/shawndeng-homelab/trade-system/commit/c46f6586223bd49a75379a3b99759a95cd639861)) - ShawnDeng-code

- - -

## [0.2.0](https://github.com/shawndeng-homelab/trade-system/compare/903be78759d59763afd73e52de1c3640da07aee8..0.2.0) - 2026-07-01
### Package updates
- [trade-system-venues-0.2.0](packages/trade-system-venues) bumped to [trade-system-venues-0.2.0](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-venues-0.1.1..trade-system-venues-0.2.0)
### Global changes
#### Bug Fixes
- default private PyPI publish URL to pypiserver.shawndeng.cc - ([d4be70c](https://github.com/shawndeng-homelab/trade-system/commit/d4be70c5087581f94f2376b863615107fdeec5cd)) - colyerdeng
#### Refactoring
- **(ibkr)** depend on nautilus-trader[ib], forbid in-function imports, document env - ([903be78](https://github.com/shawndeng-homelab/trade-system/commit/903be78759d59763afd73e52de1c3640da07aee8)) - colyerdeng

- - -

## [0.1.1](https://github.com/shawndeng-homelab/trade-system/compare/5235a9240ae8ad090f6b59fde9f76ff36da2cfce..0.1.1) - 2026-07-01
### Package updates
- [trade-system-venues-0.1.1](packages/trade-system-venues) bumped to [trade-system-venues-0.1.1](https://github.com/shawndeng-homelab/trade-system/compare/trade-system-venues-0.1.0..trade-system-venues-0.1.1)
### Global changes
#### Bug Fixes
- include trade-system-venues in mkdocs API reference - ([ef053b5](https://github.com/shawndeng-homelab/trade-system/commit/ef053b53a909f7670b2c51541662bd3850b9be67)) - colyerdeng
- discover docs packages via --all-packages instead of hardcoded paths - ([5235a92](https://github.com/shawndeng-homelab/trade-system/commit/5235a9240ae8ad090f6b59fde9f76ff36da2cfce)) - colyerdeng

- - -

## [0.1.0](https://github.com/shawndeng-homelab/trade-system/compare/d1057379128154671e23317ff8e3269deb04b469..0.1.0) - 2026-07-01
### Package updates
- [trade-system-venues](packages/trade-system-venues) bumped to [trade-system-venues-0.1.0](https://github.com/shawndeng-homelab/trade-system/compare/98859a9af066acb7867d3eba6e4dba167c5725af..trade-system-venues-0.1.0)
### Global changes
#### Bug Fixes
- register trade-system-venues package with cocogitto - ([7735d2f](https://github.com/shawndeng-homelab/trade-system/commit/7735d2feb4cf7aa953d2ea7160398ed9fccf3af7)) - colyerdeng
#### Continuous Integration
- install all workspace packages so nautilus_trader is available in tests - ([d51bf07](https://github.com/shawndeng-homelab/trade-system/commit/d51bf07e0c4cf96c630f065d64ba434a011b3e2d)) - colyerdeng
#### Features
- scaffold trade-system-venues package for Binance/IBKR fee & financing - ([740f4dc](https://github.com/shawndeng-homelab/trade-system/commit/740f4dc1592ffa17e9cafa85a3eb672355fd8956)) - colyerdeng
#### Miscellaneous Chores
- initial commit from repo-scaffold [skip ci] - ([98859a9](https://github.com/shawndeng-homelab/trade-system/commit/98859a9af066acb7867d3eba6e4dba167c5725af)) - repo-scaffold
- document cog.toml package fields (zh) and ignore .venv/ - ([d105737](https://github.com/shawndeng-homelab/trade-system/commit/d1057379128154671e23317ff8e3269deb04b469)) - colyerdeng
#### Style
- lint code - ([05715e4](https://github.com/shawndeng-homelab/trade-system/commit/05715e4c12d7c20feb3d8ed6b6802d088635aed2)) - colyerdeng

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).