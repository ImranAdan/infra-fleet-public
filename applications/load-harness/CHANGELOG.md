# Changelog

## [1.6.0](https://github.com/your-org/infra-fleet/compare/v1.5.3...v1.6.0) (2026-01-04)


### Features

* **load-harness:** add worker abstractions and job manager ([d86b8b6](https://github.com/your-org/infra-fleet/commit/d86b8b69088141a4d0c7772bed579b2ea384cb28))
* **load-harness:** security fixes and test infrastructure improvements ([e8caee5](https://github.com/your-org/infra-fleet/commit/e8caee5cd43e5cdd2469481a4c132be5956c1b72))


### Bug Fixes

* **tests:** address CodeRabbit review comments ([86c384e](https://github.com/your-org/infra-fleet/commit/86c384ee235fa1a24491f017dcfefb8bf1d40dc5))
* **tests:** enable debug mode in test fixtures for HSTS behavior ([c23812e](https://github.com/your-org/infra-fleet/commit/c23812e5ba9a7edb90e611920686562fdc5b157b))
* **tests:** test_get_active_count_with_job now calls get_active_count() ([e7f7cd6](https://github.com/your-org/infra-fleet/commit/e7f7cd680658f87c605e785f767877e630dd236d))

## [1.5.3](https://github.com/your-org/infra-fleet/compare/v1.5.2...v1.5.3) (2026-01-03)


### Bug Fixes

* **load-harness:** add ProxyFix for HTTPS session cookies ([868a41e](https://github.com/your-org/infra-fleet/commit/868a41e1e637580cfcd9e709db4923122420e53c))
* **load-harness:** add ProxyFix for HTTPS session cookies ([8a0cef9](https://github.com/your-org/infra-fleet/commit/8a0cef9938cf31b4f86d990e351a653399f99fe1))

## [1.5.2](https://github.com/your-org/infra-fleet/compare/v1.5.1...v1.5.2) (2026-01-02)


### Bug Fixes

* **dashboard:** use correct port for cluster distributed load test ([b07d935](https://github.com/your-org/infra-fleet/commit/b07d93541b380d36a8afce62525832ed864282c6))

## [1.5.1](https://github.com/your-org/infra-fleet/compare/v1.5.0...v1.5.1) (2026-01-01)


### Bug Fixes

* **load-harness:** increase gunicorn timeout for cluster load tests ([ee24dc1](https://github.com/your-org/infra-fleet/commit/ee24dc127d0f2de36b4b68cb1601a7b847df2314))
* **load-harness:** increase gunicorn timeout for cluster load tests ([62eca13](https://github.com/your-org/infra-fleet/commit/62eca130a8ce1b0fb5c2c40acf019ac0ff27e9c0))

## [1.5.0](https://github.com/your-org/infra-fleet/compare/v1.4.2...v1.5.0) (2026-01-01)


### Features

* **security:** implement security headers in Flask + add SRI ([#307](https://github.com/your-org/infra-fleet/issues/307)) ([62e56af](https://github.com/your-org/infra-fleet/commit/62e56afe734d8937b50852291a9f0f41f9669145))

## [1.4.2](https://github.com/your-org/infra-fleet/compare/v1.4.1...v1.4.2) (2025-12-28)


### Bug Fixes

* **security:** static code audit hardening ([#297](https://github.com/your-org/infra-fleet/issues/297)) ([40798e0](https://github.com/your-org/infra-fleet/commit/40798e012a6d107507341454c9bd0ca2fc26484f))

## [1.4.1](https://github.com/your-org/infra-fleet/compare/v1.4.0...v1.4.1) (2025-12-27)


### Bug Fixes

* **canary:** route load test through NGINX, fix metrics auth, add docs ([#291](https://github.com/your-org/infra-fleet/issues/291)) ([f662303](https://github.com/your-org/infra-fleet/commit/f6623036ca00e0ab566878fce8f9d54cd9e704e7))

## [1.4.0](https://github.com/your-org/infra-fleet/compare/v1.3.3...v1.4.0) (2025-12-27)


### Features

* **ui:** persist active jobs to localStorage + enable rollback test ([#285](https://github.com/your-org/infra-fleet/issues/285)) ([1058175](https://github.com/your-org/infra-fleet/commit/10581758aaf0571dd4492d60ed171ea8c66130be))

## [1.3.3](https://github.com/your-org/infra-fleet/compare/v1.3.2...v1.3.3) (2025-12-27)


### Bug Fixes

* **ui:** resolve session cookie not sent with HTMX requests ([#282](https://github.com/your-org/infra-fleet/issues/282)) ([b116690](https://github.com/your-org/infra-fleet/commit/b116690cbc3e21638cefb0b6a34fc5d3465c5cad))

## [1.3.2](https://github.com/your-org/infra-fleet/compare/v1.3.1...v1.3.2) (2025-12-27)


### Bug Fixes

* **nginx:** enable metrics for host-less ingresses ([#279](https://github.com/your-org/infra-fleet/issues/279)) ([da3f6bc](https://github.com/your-org/infra-fleet/commit/da3f6bc5cdc0ed69154b4b56c15abb7f690e7ced))

## [1.3.1](https://github.com/your-org/infra-fleet/compare/v1.3.0...v1.3.1) (2025-12-27)


### Bug Fixes

* **flagger:** configure NGINX correctly for progressive delivery ([#277](https://github.com/your-org/infra-fleet/issues/277)) ([6f8822b](https://github.com/your-org/infra-fleet/commit/6f8822b8c4fad51331c31c842d53aa5cd00450cf))

## [1.3.0](https://github.com/your-org/infra-fleet/compare/v1.2.0...v1.3.0) (2025-12-26)


### Features

* **load-harness:** add session-based auth for browser UI ([#271](https://github.com/your-org/infra-fleet/issues/271)) ([26a35fa](https://github.com/your-org/infra-fleet/commit/26a35fa8f56f02d21a56cda3cf1131cf008964a3))

## [1.2.0](https://github.com/your-org/infra-fleet/compare/v1.1.1...v1.2.0) (2025-12-26)


### Features

* **load-harness:** add API key auth and chaos injection ([#268](https://github.com/your-org/infra-fleet/issues/268)) ([6ef70d2](https://github.com/your-org/infra-fleet/commit/6ef70d2f7c1fa6b015e640cc05e5defbdb52e6bc))
* **load-harness:** inject APP_VERSION at build time ([#269](https://github.com/your-org/infra-fleet/issues/269)) ([60b4809](https://github.com/your-org/infra-fleet/commit/60b4809fa86dd9ddb61b2f02a1d4d6af9242a51e))


### Bug Fixes

* **load-harness:** make /apidocs and /ui public endpoints ([#270](https://github.com/your-org/infra-fleet/issues/270)) ([524877e](https://github.com/your-org/infra-fleet/commit/524877e7baabbf9dd651ebbe9b3c45c035ccd35c))
* **release:** correct changelog-path in release-please config ([76453e9](https://github.com/your-org/infra-fleet/commit/76453e9f3d20cefb29f2d8ad0c232cb89fd8e8f1))

## [1.1.1](https://github.com/your-org/infra-fleet/compare/v1.1.0...v1.1.1) (2025-12-22)


### Bug Fixes

* **load-harness:** add explicit 200 status to health endpoint ([#231](https://github.com/your-org/infra-fleet/issues/231)) ([50a766f](https://github.com/your-org/infra-fleet/commit/50a766f8ca5711889765660067f6c733bc3b7aea))

## [1.1.0](https://github.com/your-org/infra-fleet/compare/v1.0.1...v1.1.0) (2025-12-22)


### Features

* **load-harness:** add /ready endpoint for Kubernetes readiness probes ([#225](https://github.com/your-org/infra-fleet/issues/225)) ([86917a2](https://github.com/your-org/infra-fleet/commit/86917a232bb0f21108f7a357952b0d5c0633235d))
* **load-harness:** enhance /version endpoint with deployment tracking ([#224](https://github.com/your-org/infra-fleet/issues/224)) ([26044b0](https://github.com/your-org/infra-fleet/commit/26044b0af61486b6d7f403087b294951d7025f48))

## [1.0.1](https://github.com/your-org/infra-fleet/compare/v1.0.0...v1.0.1) (2025-12-21)


### Bug Fixes

* **ci:** remove path filters to allow tag builds ([1082522](https://github.com/your-org/infra-fleet/commit/108252271ccb891cdcc97b6e012bf19c5098eb86))

## [1.0.0](https://github.com/your-org/infra-fleet/compare/v0.1.0...v1.0.0) (2025-12-21)


### ⚠ BREAKING CHANGES

* **load-harness:** API endpoints renamed and parameters changed

### Features

* Add /load/memory endpoint for memory load testing ([#141](https://github.com/your-org/infra-fleet/issues/141)) ([99683c6](https://github.com/your-org/infra-fleet/commit/99683c6b6819d8969c4e9d3f8d304e7d76a794d1))
* Add sustained CPU load endpoint with multiprocessing ([#183](https://github.com/your-org/infra-fleet/issues/183)) ([dfea9a6](https://github.com/your-org/infra-fleet/commit/dfea9a68a6a91304f2eabc831ee482323f0df5e8))
* **dashboard:** Add Load Testing Overview dashboard with HPA and node metrics ([#181](https://github.com/your-org/infra-fleet/issues/181)) ([1657643](https://github.com/your-org/infra-fleet/commit/1657643b50604a1f1ddc53a1081adb1c3e0f2881))
* **dashboard:** Add pod capacity and pending pods panels ([#186](https://github.com/your-org/infra-fleet/issues/186)) ([ca96ec9](https://github.com/your-org/infra-fleet/commit/ca96ec98b5d939b0a3615327d270d083af951050))
* **dashboard:** Implement Phase 1 - Project Foundation ([#194](https://github.com/your-org/infra-fleet/issues/194)) ([68ccf52](https://github.com/your-org/infra-fleet/commit/68ccf52209caee9a6c123b2673db00b5b5b7ca95))
* Improve Grafana dashboard clarity and add aggregate metrics ([#169](https://github.com/your-org/infra-fleet/issues/169)) ([bb2ee2c](https://github.com/your-org/infra-fleet/commit/bb2ee2cdaf62664c34dcf08397a105c2b96190c2))
* **load-harness:** Add avg/max metrics and local vs cluster explanations ([#211](https://github.com/your-org/infra-fleet/issues/211)) ([cebbef0](https://github.com/your-org/infra-fleet/commit/cebbef0580decf750951793cdddd5367e9c4c414))
* **load-harness:** Add dark mode toggle to dashboard UI ([#206](https://github.com/your-org/infra-fleet/issues/206)) ([be4d814](https://github.com/your-org/infra-fleet/commit/be4d814b7a0edf497fa453a22d8d5f10edb43d9a))
* **load-harness:** Add live metrics, cluster load, and enhanced UI ([#201](https://github.com/your-org/infra-fleet/issues/201)) ([#202](https://github.com/your-org/infra-fleet/issues/202)) ([0273060](https://github.com/your-org/infra-fleet/commit/02730602a57f848bdc769206ea4ee69416c51e5b))
* **load-harness:** Add OpenAPI/Swagger documentation ([#188](https://github.com/your-org/infra-fleet/issues/188)) ([db8a8a9](https://github.com/your-org/infra-fleet/commit/db8a8a967450e039477b464b33916d355b19cc5b))
* **load-harness:** Add Pod Monitor panel for Cluster Load tab ([10d7e92](https://github.com/your-org/infra-fleet/commit/10d7e921659ca7bedab84f727ddf67c004c0d785))
* **load-harness:** Add synchronous CPU work endpoint for distributed load testing ([#196](https://github.com/your-org/infra-fleet/issues/196)) ([513b8ef](https://github.com/your-org/infra-fleet/commit/513b8eff8ae0d7fc6d29a05d31fd894785c3c1b3))
* **load-harness:** Increase pod memory limit to 1Gi and cap UI slider ([#212](https://github.com/your-org/infra-fleet/issues/212)) ([6497d16](https://github.com/your-org/infra-fleet/commit/6497d1661aca5aff735bbb078a4eb7fe026c6366))
* **load-harness:** Make Memory Load async with UI improvements ([#209](https://github.com/your-org/infra-fleet/issues/209)) ([407b094](https://github.com/your-org/infra-fleet/commit/407b094f67df0c00169f72d307cee4f245321913))
* **release:** add semver release automation ([#218](https://github.com/your-org/infra-fleet/issues/218)) ([f7c35f1](https://github.com/your-org/infra-fleet/commit/f7c35f1dfbc538b9846c6266b0413d8b8e521356))


### Bug Fixes

* Increase liveness probe timeout and improve dashboard queries ([#168](https://github.com/your-org/infra-fleet/issues/168)) ([4cb940c](https://github.com/your-org/infra-fleet/commit/4cb940cdd814665c543c4ab08f1dc724163184f7))
* **load-harness:** Client-side job tracking for Active Jobs panel ([fd9a36f](https://github.com/your-org/infra-fleet/commit/fd9a36ff4f55e7adcd0559658ea883399d5c0a2f))
* **load-harness:** Fix Live Metrics and Active Jobs tracking ([#210](https://github.com/your-org/infra-fleet/issues/210)) ([566bbc3](https://github.com/your-org/infra-fleet/commit/566bbc3e07cad57bf73c10fad6be72ac3f21acb9))
* **load-harness:** Fix Prometheus URL and improve cluster load error handling ([#204](https://github.com/your-org/infra-fleet/issues/204)) ([d1eb8a6](https://github.com/your-org/infra-fleet/commit/d1eb8a6417d06be459d2d2c745db651f8753bcd5))
* **load-harness:** Fix Request Rate Prometheus query labels ([#213](https://github.com/your-org/infra-fleet/issues/213)) ([a86da86](https://github.com/your-org/infra-fleet/commit/a86da86a37e1650f7d743188a6367212154a2da6))
* **load-harness:** Improve stability under load and enable HPA scaling ([#200](https://github.com/your-org/infra-fleet/issues/200)) ([b363f69](https://github.com/your-org/infra-fleet/commit/b363f694e403fd514b621235c87171fccc8676f5))
* **load-harness:** Use PORT env var for internal API calls ([14cece2](https://github.com/your-org/infra-fleet/commit/14cece282126306dbf2d9897fa161a366a17cdf7))


### Code Refactoring

* **load-harness:** Simplify CPU load API and add core detection ([#195](https://github.com/your-org/infra-fleet/issues/195)) ([27fa435](https://github.com/your-org/infra-fleet/commit/27fa43584f2986f125c45d14561a865419f335b6))
