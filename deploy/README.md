# 部署说明

本目录用于以 Docker Compose 启停商机智能分析系统。地址、密钥和环境差异只放在本地 `.env`，不要写入源码。

## 本地 ARM 开发（Apple Silicon）

```bash
cd MaxKB
BIA_SAVE=0 bash deploy/build-and-save.sh bia-v0.1.0
# 产物标签形如 bia:bia-v0.1.0-<short-sha>-arm64

cd deploy
cp .env.example .env
# 将 BIA_IMAGE 改成刚构建的标签
mkdir -p data
docker compose up -d
```

该镜像仅用于本机验证，不要交付到 x86 服务器。

网络分流（默认 `BIA_CN_MIRROR=1`）：

| 资源 | 走法 |
|---|---|
| `ghcr.io`、`docker.io` 拉基础镜像 | Docker Desktop 代理 `127.0.0.1:7890` |
| Debian apt | 阿里云镜像，不走代理 |
| PostgreSQL apt（本步不装包） | 临时关掉 pgdg 源，避免国外站或错误镜像拖垮 `apt-get update` |
| npm | `registry.npmmirror.com`，不走代理 |
| pip / uv | 清华 PyPI，不走代理 |

关闭国内源时：`BIA_CN_MIRROR=0 bash deploy/build-and-save.sh ...`

## 服务器目录

建议在目标机使用：

```text
/data/bia/
├── docker-compose.yml
├── .env
├── data/          # 挂载到容器 /opt/maxkb
├── images/        # docker save 产物
└── MaxKB/         # 源码，用于在服务器构建镜像
```

端口使用 `29090`。

## 商机嵌入接入开关

商机分析的业务系统嵌入能力默认关闭。保持 `.env` 中
`MAXKB_OPPORTUNITY_EMBED_ENABLED=false` 时，设置页不会显示“嵌入接入”，
嵌入客户端、令牌、会话和分析端点也会返回统一的 404 未启用结果；已有
客户端数据不会被删除。确认有正式接入方后，将该值改为 `true` 并重启服务，
即可恢复原有来源白名单、短期令牌和权限逻辑。

## 构建并保存镜像

版本号和短提交号在**本机**算好再带到服务器。174 上不要安装、也不要使用 git。

```bash
# 本机
SHA=$(git rev-parse --short HEAD)

# 服务器（源码用 tar/scp 同步后）
cd /data/bia/MaxKB
bash deploy/build-and-save.sh bia-v0.1.0 "$SHA" /data/bia/images
```

每次重新构建后都会在 `/data/bia/images` 生成可追溯 tar。

## 制作 x86 离线一键安装包

在构建完成且镜像已加载到本机后执行：

```bash
export BIA_PLATFORM=linux/amd64
bash deploy/package-offline-release.sh \
  bia-v0.3.0 <short-sha> \
  images/bia_bia-v0.3.0_<short-sha>_amd64.tar \
  releases
```

输出的 `bia-<version>-<sha>-amd64.tar.gz` 上传服务器后，只需解压并执行
`sudo ./install.sh`。详细要求见 `deploy/OFFLINE_INSTALL.md`。

ARM 构建机内存不足以在 QEMU 中执行前端编译时，可先在宿主机执行前端
`type-check`、`build-only`、`build-chat`，再使用
`installer/Dockerfile-stage-build` 导出 x86 后端阶段，并通过
`installer/Dockerfile-prebuilt-ui` 合并 `ui/dist`。前端产物是静态文件，
该方式不会把 ARM 原生二进制带入 amd64 运行镜像。

## 启停

```bash
cd /data/bia
cp MaxKB/deploy/docker-compose.yml .
cp MaxKB/deploy/.env.example .env
# 将 BIA_IMAGE 改为刚构建的标签，例如 bia:bia-v0.1.0-<short-sha>-amd64
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

默认管理员账号以镜像首次初始化结果为准，不要把密码提交到仓库。
