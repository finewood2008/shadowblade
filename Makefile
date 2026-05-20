# 火花 · Huohua · 命令统一入口

.PHONY: help install build build-electron build-web smoke check release clean

VERSION ?= 0.8.0

help:  ## 显示所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[35m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## 安装所有子项目依赖
	cd project/aitoearn-electron && npm install --no-audit --no-fund
	cd project/aitoearn-web && npm install --no-audit --no-fund

build: build-electron build-web  ## 全量打包

build-electron:  ## 打 macOS dmg/zip
	cd project/aitoearn-electron && npm run build:notsc

build-web:  ## 打 web standalone
	cd project/aitoearn-web && npm run build

smoke:  ## 验 dmg metadata (arm64 + x64)
	./scripts/smoke_test.sh arm64
	./scripts/smoke_test.sh x64

check:  ## 品牌残留守门
	./scripts/check_brand_residue.sh

release: smoke check  ## 准备 GitHub Release（产物 + SHA256）
	./scripts/prepare_release.sh $(VERSION)

clean:  ## 清理 build 产物
	rm -rf project/aitoearn-electron/release
	rm -rf project/aitoearn-electron/dist
	rm -rf project/aitoearn-electron/dist-electron
	rm -rf project/aitoearn-web/.next
	rm -rf dist/
