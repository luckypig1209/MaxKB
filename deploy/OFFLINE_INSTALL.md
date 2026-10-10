# 商机智能分析系统 x86 离线安装包

本安装包适用于 `x86_64/amd64` Linux 服务器。服务器无需源码、Git、Node.js、Python 或外网，只需提前安装 Docker 和 Docker Compose。

## 一键安装

```bash
tar -xzf bia-*.tar.gz
cd bia-*-amd64
sudo ./install.sh
```

默认安装目录为 `/data/bia`，默认访问端口为 `29090`：

```text
http://<服务器IP>:29090/admin/
```

指定安装目录或端口：

```bash
sudo INSTALL_ROOT=/opt/bia BIA_PORT_OVERRIDE=8080 ./install.sh
```

安装脚本会校验文件摘要和 CPU 架构、导入固定版本镜像、保留已有 `.env` 与 `data`，并等待容器健康。首次安装会自动生成数据库、Redis 和应用密钥。

## 常用运维命令

```bash
cd /data/bia
sudo docker compose ps
sudo docker compose logs -f --tail=200 bia
sudo docker compose restart bia
sudo docker compose down
sudo docker compose up -d
```

## 安装前要求

- Linux x86_64/amd64；
- Docker Engine 可用；
- Docker Compose v2，或兼容的 `docker-compose`；
- 建议至少 4 核 CPU、8 GB 内存、50 GB 可用磁盘；
- 默认端口 `29090` 可从客户端访问；
- `/data/bia` 所在磁盘需要持久化和定期备份。

## 数据与升级安全

- 业务数据位于 `/data/bia/data`，重新安装或升级不会主动删除该目录；
- 安装前的 `.env` 和 `docker-compose.yml` 会生成带时间戳的备份；
- 请勿直接删除 `data`，也不要用空目录覆盖它；
- 上线前仍需在目标 x86 服务器完成登录、模型调用、知识检索、商机分析和异步任务冒烟测试。
