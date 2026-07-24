# Changelog

All notable changes to this project will be documented in this file. 

## [2.1.6](https://github.com/rudderlabs/rudder-sdk-python/compare/v2.1.5...v2.1.6) (2026-07-24)


### Miscellaneous

* **codeowners:** set sdk_team as code owners ([#114](https://github.com/rudderlabs/rudder-sdk-python/issues/114)) ([7bab8aa](https://github.com/rudderlabs/rudder-sdk-python/commit/7bab8aa77da97447d532283d6259c6097a0d758f))

## [2.1.5](https://github.com/rudderlabs/rudder-sdk-python/compare/v2.1.4...v2.1.5) (2026-07-06)


### Bug Fixes

* **vuln:** pin and bump action refs (SEC-171) ([9b5402b](https://github.com/rudderlabs/rudder-sdk-python/commit/9b5402b8b1eaa8696e04a35ae44078caa212d498))


### Miscellaneous

* add DeepWiki badge to README.md ([b932c09](https://github.com/rudderlabs/rudder-sdk-python/commit/b932c09b0a795ca946b66d42246093fc5200befc))
* add DeepWiki badge to README.md ([50d2487](https://github.com/rudderlabs/rudder-sdk-python/commit/50d2487698fd98357b87e8a6dd083f4d4ab0dfc0))
* apply security best practices from step security ([8873515](https://github.com/rudderlabs/rudder-sdk-python/commit/8873515a5249f4340d7c6632725d9ffb70cc7c9b))
* apply security best practices from step security ([#56](https://github.com/rudderlabs/rudder-sdk-python/issues/56)) ([8873515](https://github.com/rudderlabs/rudder-sdk-python/commit/8873515a5249f4340d7c6632725d9ffb70cc7c9b))
* apply security best practices from step security ([#59](https://github.com/rudderlabs/rudder-sdk-python/issues/59)) ([3b16a40](https://github.com/rudderlabs/rudder-sdk-python/commit/3b16a4034716c3e7d6095c9c2a32f6dd3fafb575))
* resolve setup.py check warning ([6608273](https://github.com/rudderlabs/rudder-sdk-python/commit/66082737b0e46d88e48b0b153b8d9780101f3108))
* sdk-4991 migrate python sdk to release-please ([de8be0d](https://github.com/rudderlabs/rudder-sdk-python/commit/de8be0ddff397ede0bd9253b207068c195eed956))
* sdk-4991 migrate python sdk to release-please ([e2cbb82](https://github.com/rudderlabs/rudder-sdk-python/commit/e2cbb829e2dff676da60b688ad611585a0b0e13f))
* **vuln:** pin and bump action refs (SEC-171) ([f494a56](https://github.com/rudderlabs/rudder-sdk-python/commit/f494a56c84d8abff61bfd93ef14c4ac7572bf6bf))
* **vuln:** scope workflow permissions to least privilege (SEC-167) ([dd8c29d](https://github.com/rudderlabs/rudder-sdk-python/commit/dd8c29d72e070168a87c7b2e3dae2e96576935bd))
* **vuln:** scope workflow permissions to least privilege (SEC-167) ([4a1e87a](https://github.com/rudderlabs/rudder-sdk-python/commit/4a1e87a95677dcbb8320e6db6ec151fa14484de3))
* **vuln:** zizmor --fix=all findings (SEC-199) ([44c0dac](https://github.com/rudderlabs/rudder-sdk-python/commit/44c0dac2e807ff54f09144b7bd14e9abf853f3eb))
* **vuln:** zizmor --fix=all findings (SEC-199) ([ed592e0](https://github.com/rudderlabs/rudder-sdk-python/commit/ed592e02b02b29db8308c3cd258235e954cafdb8))

## [2.0.0]
## Features
- Update SDK with latest code.
- Update tests with latest dependencies 
## Breaking Changes
- Updated package name to rudderstack.analytics
- Added optional gzip capabilities
- Batch size reduced to 500KB
- Max message size reduced to 32KB
- flush_at is now renamed to upload_size
- flush_interval renamed to upload_interval
- Removed support for python 3.6

## [2.0.1]
## Fixes
- Default gzip value is set to True

## [2.0.2]
## Fixes
- Fixed dataPlaneUrl setter issue [#20](https://github.com/rudderlabs/rudder-sdk-python/issues/20)

## [2.1.0]
## Fixes
- Fixed versions of dependencies. Moved to use flexible depencencies.
- Updated License

## [2.1.1]
## Fixes
- Fixed versions of dotenv dependency. Moved to use a higher upper limit (2.0.0)
- Updated License
