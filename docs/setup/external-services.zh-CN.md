# Scholens 外部服务申请与配置

本文档用于本地开发环境。生产环境应使用独立资源、最小权限角色和密钥托管服务，不要复用开发凭证。

## 1. AWS S3

### 创建开发 Bucket

1. 登录 [AWS Console](https://console.aws.amazon.com/)。
2. 进入 **S3 → Buckets → Create bucket**。
3. 建议命名为 `scholens-dev-<aws-account-id>-<region>`，并选择离服务较近的 Region。
4. 保持 **Object Ownership: Bucket owner enforced**、**Block all public access** 全部开启，并启用默认加密。
5. 在 Bucket 的 **Permissions → CORS** 中加入：

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": [
      "http://localhost:3000",
      "https://scholens.sanchezcloud.net"
    ],
    "ExposeHeaders": [
      "Accept-Ranges",
      "Content-Length",
      "Content-Range",
      "ETag"
    ],
    "MaxAgeSeconds": 3600
  }
]
```

### 创建本地开发凭证

进入 **IAM → Users → Create user**，创建仅供 Scholens 本地开发使用的用户，并附加下列最小权限策略。把 `YOUR_BUCKET` 替换成实际 Bucket 名：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET/*"
    }
  ]
}
```

在该用户的 **Security credentials → Create access key** 创建开发凭证，并分别写入 `server/.env` 与 `jobs/.env`：

```dotenv
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-southeast-1
S3_BUCKET_NAME=scholens-dev-<aws-account-id>-<region>
CLOUDFLARE_BUCKET_NAME=scholens-dev-<aws-account-id>-<region>.s3.<region>.amazonaws.com
```

`CLOUDFLARE_BUCKET_NAME` 在现有代码中实际表示文件访问主机名，本地直接填写
S3 区域主机名即可；生产环境接入 CDN 后再填写 CDN 域名。生产部署不要创建长期
Access Key；为 EC2/ECS 工作负载绑定 IAM Role。

官方资料：[创建 Bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html)、[S3 IAM 策略示例](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security_iam_id-based-policy-examples.html)、[Access Key 管理](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html)。

## 2. MinerU

1. 打开 [MinerU](https://mineru.net/) 并注册或登录。
2. 进入 [API Token 页面](https://mineru.net/apiManage/token) 创建 Token。
3. 在 [API 文档](https://mineru.net/apiManage/docs) 中确认异步解析接口及当前限制。
4. 将 Token 写入 `jobs/.env`：

```dotenv
MINERU_API_TOKEN=
MINERU_API_BASE_URL=https://mineru.net/api/v4
MINERU_MODEL_VERSION=vlm
```

Scholens Jobs 会给 MinerU 提交一个短期 S3 签名 URL，轮询解析结果，并将 Markdown 与解析 ZIP 重新保存到自己的 S3。真实论文会离开 AWS 边界并交给 MinerU 处理，因此在上传敏感或未公开论文前，需要确认其隐私条款和数据保留政策。

## 3. MOSS Voice

1. 打开 [MOSS 平台](https://platform.mosi.cn/) 并注册或登录。
2. 在控制台进入 API Key 管理，创建名为 `scholens-development` 的 Key。
3. 在 Voice/声音管理或 Playground 中选择一个已有声音；若要自定义声音，按官方 Voice API 上传合规的参考音频，并保存接口返回的 `voice_id`。
4. 将 Key 与 `voice_id` 写入 `server/.env`：

```dotenv
MOSS_API_KEY=
MOSS_API_BASE_URL=https://api.mosi.cn/v1
MOSS_TTS_MODEL=moss-tts
MOSS_VOICE_ID=
```

Scholens 调用 `POST /v1/audio/speech` 创建异步语音任务，并轮询任务状态。MOSS 合成本身不计入 Scholens Token Credits；生成音频文稿的 DeepSeek 调用正常计费。

官方资料：[MOSS Voice 文档](https://platform.mosi.cn/docs/getting-started/overview/)。

## 4. DeepSeek

在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API Key，并写入 `server/.env` 与 `jobs/.env`：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_STANDARD_MODEL=deepseek-v4-flash
DEEPSEEK_DEEP_MODEL=deepseek-v4-pro
```

API Key 只保存在未提交的 `.env` 或生产密钥服务中，不要粘贴到聊天、Issue、日志或 Git 历史。模型 ID 可能调整，上线前应再次核对 [DeepSeek 官方 API 文档](https://api-docs.deepseek.com/)。
