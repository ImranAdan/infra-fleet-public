# Changelog

## [1.10.0](https://github.com/ImranAdan/infra-fleet-public/compare/v1.9.0...v1.10.0) (2026-09-30)


### Features

* **control-plane:** application dashboard with on-demand launch ([7d3de74](https://github.com/ImranAdan/infra-fleet-public/commit/7d3de7402802c0edfd83ef4b9aeaa8b474451ec7))


### Bug Fixes

* **aws:** align teardown with gateway routing ([a887e9e](https://github.com/ImranAdan/infra-fleet-public/commit/a887e9e3b7fa31bd5ea07da495736ae0c8ab844c))
* **control-plane:** isolate and prove on-demand apps ([da1cf0b](https://github.com/ImranAdan/infra-fleet-public/commit/da1cf0b45aa60d23e7110a96c8776885b58aec47))

## [1.9.0](https://github.com/ImranAdan/infra-fleet-public/compare/v1.8.2...v1.9.0) (2026-09-27)


### Features

* **staging:** scale workers on demand and release them nightly ([6bbf63f](https://github.com/ImranAdan/infra-fleet-public/commit/6bbf63fed34af7a9f20e34a38deaaafdf2796864))


### Bug Fixes

* **iam:** let automation manage worker scheduled actions ([7489681](https://github.com/ImranAdan/infra-fleet-public/commit/7489681e5379018a4ae9d5c312aeac4ac79bf612))

## [1.8.2](https://github.com/ImranAdan/infra-fleet-public/compare/v1.8.1...v1.8.2) (2026-09-27)


### Bug Fixes

* **release:** keep tag logic with application ([6c3a4df](https://github.com/ImranAdan/infra-fleet-public/commit/6c3a4df67bb7bdcf476148cc4b2a43ed4002e0f2))
* **release:** select manual image version ([72104f0](https://github.com/ImranAdan/infra-fleet-public/commit/72104f04fae75997f7eaed85b719ff0c3f8c982a))
* **release:** tighten image tag validation ([e2bdcad](https://github.com/ImranAdan/infra-fleet-public/commit/e2bdcad52b46222ce7720d1f7004955e0af9be6c))

## [1.8.1](https://github.com/ImranAdan/infra-fleet-public/compare/v1.8.0...v1.8.1) (2026-09-27)


### Bug Fixes

* **load-harness:** preserve probe capacity under CPU work ([#101](https://github.com/ImranAdan/infra-fleet-public/issues/101)) ([1bccdd9](https://github.com/ImranAdan/infra-fleet-public/commit/1bccdd91683e48d03b771221ff01243d5a6818ca))

## [1.8.0](https://github.com/ImranAdan/infra-fleet-public/compare/v1.7.1...v1.8.0) (2026-09-25)


### Features

* make the application swappable through an app contract ([cea2278](https://github.com/ImranAdan/infra-fleet-public/commit/cea22780d7ae2ee42a7e028c17bba5bdfcbc4778))
* **observability:** provision Grafana dashboards from Git ([4107fb7](https://github.com/ImranAdan/infra-fleet-public/commit/4107fb7c01b07b1eb8c80c0230fb6a273b2954a3))


### Bug Fixes

* **load-harness:** aggregate metrics across gunicorn workers ([e225f4c](https://github.com/ImranAdan/infra-fleet-public/commit/e225f4c216ba19a2af86a3b583644de937a246f1))
* **load-harness:** report the load and limits the app really has ([1d2e037](https://github.com/ImranAdan/infra-fleet-public/commit/1d2e03748132ca353f56efd802c120de36b41313))
* **load-harness:** set multiprocess metrics only for Gunicorn ([dbb3d33](https://github.com/ImranAdan/infra-fleet-public/commit/dbb3d33a0c1058a559535b78457d22be2c2b95ad))
* **observability:** chart pod CPU and memory from cAdvisor ([076b2dd](https://github.com/ImranAdan/infra-fleet-public/commit/076b2dd8d0fa4f7bdbaeb864223a86f1c66cb2e9))

## [1.7.1](https://github.com/ImranAdan/infra-fleet-public/compare/v1.7.0...v1.7.1) (2026-09-15)


### Bug Fixes

* **load-harness:** bound login tracking state ([4fb3ed1](https://github.com/ImranAdan/infra-fleet-public/commit/4fb3ed1721de7b9d1fdd52102ffc12f3d8904144))
* **load-harness:** carry job IDs and memory limits through ([58a1db1](https://github.com/ImranAdan/infra-fleet-public/commit/58a1db1c0a0fa9052b11dc661aeb8cf9f53537ea))
* **load-harness:** enforce pod memory reservations ([9d23577](https://github.com/ImranAdan/infra-fleet-public/commit/9d23577a44459f5c208661f4d07030cdeffc6d56))
* **load-harness:** pin test environment and record the aggregate memory gap ([52fe8cc](https://github.com/ImranAdan/infra-fleet-public/commit/52fe8cc09f2627afa2273978dfe1fc637c158f84))
* **load-harness:** remove dashboard self-HTTP deadlock and related defects ([99d08b4](https://github.com/ImranAdan/infra-fleet-public/commit/99d08b4e72bc83b977f95c3eae2d524136e9f730))
* **load-harness:** remove dashboard self-HTTP deadlock and related defects ([ab3509d](https://github.com/ImranAdan/infra-fleet-public/commit/ab3509da1123330ae916437bde9bc29ec7f90577))

## [1.7.0](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.5...v1.7.0) (2026-09-15)


### Features

* add local and AWS deployment profiles ([04a7ccc](https://github.com/ImranAdan/infra-fleet-public/commit/04a7ccc9fa87e7a0aad0b9b50c5d1e984be43359))
* compose shared platform with local and AWS profiles ([b68fe25](https://github.com/ImranAdan/infra-fleet-public/commit/b68fe2551f6f930d3ac2fe34fa85136aab006f99))

## [1.6.5](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.4...v1.6.5) (2026-09-14)


### Bug Fixes

* harden plug-and-play fleet adoption ([0979268](https://github.com/ImranAdan/infra-fleet-public/commit/09792680b8645373e9c5fa732323d922adfd2a75))
* make fleet template adoption deterministic ([ec3d932](https://github.com/ImranAdan/infra-fleet-public/commit/ec3d932b562f0b8a013737b708b4513d895bb012))

## [1.6.4](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.3...v1.6.4) (2026-09-10)


### Bug Fixes

* **local-dev:** make the documented first command work on a clean clone ([613b84e](https://github.com/ImranAdan/infra-fleet-public/commit/613b84e0b1cfd476724386bb40a71e6ac50c3eb6))
* **local-dev:** make the documented first command work on a clean clone ([ab9dc37](https://github.com/ImranAdan/infra-fleet-public/commit/ab9dc37ac44e3db5fb561109fbb58e30fdfb7c1b))
* **template:** make the documented configuration real ([08c15f2](https://github.com/ImranAdan/infra-fleet-public/commit/08c15f2880da24f0bf134df4e41e5644559ad085))
* **template:** make the documented configuration real ([b615c79](https://github.com/ImranAdan/infra-fleet-public/commit/b615c797f1d18b3f0b61184dd6dae446ab3102f4))

## [1.6.3](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.2...v1.6.3) (2026-09-10)


### Bug Fixes

* **load-harness:** derive site-packages path instead of hardcoding it ([1317367](https://github.com/ImranAdan/infra-fleet-public/commit/13173679b303493158455a09c43129e668b9231b))

## [1.6.2](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.1...v1.6.2) (2026-09-10)


### Bug Fixes

* **load-harness:** repair the container security scan and the image it scans ([256f2d9](https://github.com/ImranAdan/infra-fleet-public/commit/256f2d9e9d400e46cd6a562488d5837d4743c34c))

## [1.6.1](https://github.com/ImranAdan/infra-fleet-public/compare/v1.6.0...v1.6.1) (2026-09-10)


### Bug Fixes

* apply security patches for Trivy scan vulnerabilities ([f03f7ad](https://github.com/ImranAdan/infra-fleet-public/commit/f03f7ad5ae968d80a02a5e9a748f8e19bcf2d840))

> Entries through 1.6.0 predate this public repository history. Source issue
> and commit labels remain as historical text; unavailable placeholder links
> have been removed.

## 1.6.0 (2026-01-04)


### Features

* **load-harness:** add worker abstractions and job manager (d86b8b6)
* **load-harness:** security fixes and test infrastructure improvements (e8caee5)


### Bug Fixes

* **tests:** address CodeRabbit review comments (86c384e)
* **tests:** enable debug mode in test fixtures for HSTS behavior (c23812e)
* **tests:** test_get_active_count_with_job now calls get_active_count() (e7f7cd6)

## 1.5.3 (2026-01-03)


### Bug Fixes

* **load-harness:** add ProxyFix for HTTPS session cookies (868a41e)
* **load-harness:** add ProxyFix for HTTPS session cookies (8a0cef9)

## 1.5.2 (2026-01-02)


### Bug Fixes

* **dashboard:** use correct port for cluster distributed load test (b07d935)

## 1.5.1 (2026-01-01)


### Bug Fixes

* **load-harness:** increase gunicorn timeout for cluster load tests (ee24dc1)
* **load-harness:** increase gunicorn timeout for cluster load tests (62eca13)

## 1.5.0 (2026-01-01)


### Features

* **security:** implement security headers in Flask + add SRI (#307) (62e56af)

## 1.4.2 (2025-12-28)


### Bug Fixes

* **security:** static code audit hardening (#297) (40798e0)

## 1.4.1 (2025-12-27)


### Bug Fixes

* **canary:** route load test through NGINX, fix metrics auth, add docs (#291) (f662303)

## 1.4.0 (2025-12-27)


### Features

* **ui:** persist active jobs to localStorage + enable rollback test (#285) (1058175)

## 1.3.3 (2025-12-27)


### Bug Fixes

* **ui:** resolve session cookie not sent with HTMX requests (#282) (b116690)

## 1.3.2 (2025-12-27)


### Bug Fixes

* **nginx:** enable metrics for host-less ingresses (#279) (da3f6bc)

## 1.3.1 (2025-12-27)


### Bug Fixes

* **flagger:** configure NGINX correctly for progressive delivery (#277) (6f8822b)

## 1.3.0 (2025-12-26)


### Features

* **load-harness:** add session-based auth for browser UI (#271) (26a35fa)

## 1.2.0 (2025-12-26)


### Features

* **load-harness:** add API key auth and chaos injection (#268) (6ef70d2)
* **load-harness:** inject APP_VERSION at build time (#269) (60b4809)


### Bug Fixes

* **load-harness:** make /apidocs and /ui public endpoints (#270) (524877e)
* **release:** correct changelog-path in release-please config (76453e9)

## 1.1.1 (2025-12-22)


### Bug Fixes

* **load-harness:** add explicit 200 status to health endpoint (#231) (50a766f)

## 1.1.0 (2025-12-22)


### Features

* **load-harness:** add /ready endpoint for Kubernetes readiness probes (#225) (86917a2)
* **load-harness:** enhance /version endpoint with deployment tracking (#224) (26044b0)

## 1.0.1 (2025-12-21)


### Bug Fixes

* **ci:** remove path filters to allow tag builds (1082522)

## 1.0.0 (2025-12-21)


### ⚠ BREAKING CHANGES

* **load-harness:** API endpoints renamed and parameters changed

### Features

* Add /load/memory endpoint for memory load testing (#141) (99683c6)
* Add sustained CPU load endpoint with multiprocessing (#183) (dfea9a6)
* **dashboard:** Add Load Testing Overview dashboard with HPA and node metrics (#181) (1657643)
* **dashboard:** Add pod capacity and pending pods panels (#186) (ca96ec9)
* **dashboard:** Implement Phase 1 - Project Foundation (#194) (68ccf52)
* Improve Grafana dashboard clarity and add aggregate metrics (#169) (bb2ee2c)
* **load-harness:** Add avg/max metrics and local vs cluster explanations (#211) (cebbef0)
* **load-harness:** Add dark mode toggle to dashboard UI (#206) (be4d814)
* **load-harness:** Add live metrics, cluster load, and enhanced UI (#201) (#202) (0273060)
* **load-harness:** Add OpenAPI/Swagger documentation (#188) (db8a8a9)
* **load-harness:** Add Pod Monitor panel for Cluster Load tab (10d7e92)
* **load-harness:** Add synchronous CPU work endpoint for distributed load testing (#196) (513b8ef)
* **load-harness:** Increase pod memory limit to 1Gi and cap UI slider (#212) (6497d16)
* **load-harness:** Make Memory Load async with UI improvements (#209) (407b094)
* **release:** add semver release automation (#218) (f7c35f1)


### Bug Fixes

* Increase liveness probe timeout and improve dashboard queries (#168) (4cb940c)
* **load-harness:** Client-side job tracking for Active Jobs panel (fd9a36f)
* **load-harness:** Fix Live Metrics and Active Jobs tracking (#210) (566bbc3)
* **load-harness:** Fix Prometheus URL and improve cluster load error handling (#204) (d1eb8a6)
* **load-harness:** Fix Request Rate Prometheus query labels (#213) (a86da86)
* **load-harness:** Improve stability under load and enable HPA scaling (#200) (b363f69)
* **load-harness:** Use PORT env var for internal API calls (14cece2)


### Code Refactoring

* **load-harness:** Simplify CPU load API and add core detection (#195) (27fa435)
