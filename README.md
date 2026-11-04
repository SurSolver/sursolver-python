# SurSolver for Python — captcha solver API client

Solve **reCAPTCHA v3**, **Cloudflare Turnstile**, **Cloudflare Challenge**, **GeeTest**,
**DataDome**, **AWS WAF**, **Akamai**, **Kasada** and image captchas from Python with the
official [SurSolver](https://sursolver.com) client. One call submits the captcha and returns the
token or cookie. Works with plain Python and asyncio.

```powershell
pip install sursolver
```

## Quick start

```python
from sursolver import SurSolver, TaskType

API_KEY = "YOUR_API_KEY"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)

client = SurSolver(API_KEY)

result = client.solve(
    {
        "type": TaskType.TurnstileTokenProxyLess,
        "websiteURL": "https://example.com/login",
        "websiteKey": "0x4AAAAAAA...",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["token"])
```

Send the same `userAgent` with the request that uses the result. Tokens and cookies are
single-use, so use them right away. The examples below reuse `client` and `USER_AGENT`.

## Examples

### Solve reCAPTCHA v3 in Python

```python
result = client.solve(
    {
        "type": TaskType.ReCaptchaV3TokenProxyLess,
        "websiteURL": "https://example.com/login",
        "websiteKey": "6Le-wvkS...",
        "pageAction": "login",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["gRecaptchaResponse"])
```

For reCAPTCHA v3 Enterprise use `TaskType.ReCaptchaV3EnterpriseTokenProxyLess`.

### Solve Cloudflare Turnstile

```python
result = client.solve(
    {
        "type": TaskType.TurnstileTokenProxyLess,
        "websiteURL": "https://example.com/signup",
        "websiteKey": "0x4AAAAAAA...",
        "userAgent": USER_AGENT,
    }
)
# Submit result.solution["token"] as the cf-turnstile-response form field.
```

### Bypass the Cloudflare Challenge page (cf_clearance)

```python
result = client.solve(
    {
        "type": TaskType.CloudflareChallengeCookie,
        "websiteURL": "https://example.com/protected",
        "proxy": "http://user:password@203.0.113.10:8000",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["cf_clearance"])
```

Replay the cookie through the same proxy and with the same `userAgent`.

### Solve GeeTest v4

```python
result = client.solve(
    {
        "type": TaskType.GeeTestTokenProxyLess,
        "websiteURL": "https://example.com/login",
        "captchaId": "e392e1d7fd421dc63325744d5a2b9c73",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["lot_number"], result.solution["pass_token"])
```

GeeTest v3: send `gt` and a fresh `challenge` instead of `captchaId`.

### Solve the DataDome slider

```python
result = client.solve(
    {
        "type": TaskType.DataDomeSliderCookie,
        "websiteURL": "https://example.com/",
        "captchaUrl": "https://geo.captcha-delivery.com/captcha/?initialCid=...",
        "proxy": "http://user:password@203.0.113.10:8000",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["datadome"])
```

### Get an AWS WAF token (silent challenge)

```python
result = client.solve(
    {
        "type": TaskType.AwsChallengeCookie,
        "websiteURL": "https://example.com/",
        "scriptUrl": "https://example.token.awswaf.com/example/challenge.js",
        "userAgent": USER_AGENT,
    }
)
print(result.solution["aws-waf-token"])
```

The visual AWS WAF CAPTCHA is `TaskType.AwsCaptchaCookie` and needs your proxy.

### Solve an image captcha (image to text)

```python
import base64
from pathlib import Path

result = client.solve(
    {
        "type": TaskType.ImageToTextTask,
        "module": "1",
        "body": base64.b64encode(Path("captcha.png").read_bytes()).decode(),
    }
)
print(result.solution["answer"])
```

### asyncio

```python
import asyncio
from sursolver import AsyncSurSolver, TaskType


async def main() -> None:
    async with AsyncSurSolver(API_KEY) as client:
        result = await client.solve(
            {
                "type": TaskType.TurnstileTokenProxyLess,
                "websiteURL": "https://example.com/login",
                "websiteKey": "0x4AAAAAAA...",
                "userAgent": USER_AGENT,
            }
        )
        print(result.solution["token"])


asyncio.run(main())
```

## Supported captchas

| Captcha | `task.type` | Guide |
|---|---|---|
| reCAPTCHA v3 | `ReCaptchaV3TokenProxyLess` | [recaptcha-v3](https://sursolver.com/solvers/recaptcha-v3) |
| reCAPTCHA v3 Enterprise | `ReCaptchaV3EnterpriseTokenProxyLess` | [recaptcha-v3-enterprise](https://sursolver.com/solvers/recaptcha-v3-enterprise) |
| Cloudflare Turnstile | `TurnstileTokenProxyLess` | [turnstile](https://sursolver.com/solvers/turnstile) |
| Cloudflare Challenge | `CloudflareChallengeCookie` | [cloudflare-challenge](https://sursolver.com/solvers/cloudflare-challenge) |
| GeeTest v3 / v4 | `GeeTestTokenProxyLess` | [geetest](https://sursolver.com/solvers/geetest) |
| DataDome | `DataDomeSliderCookie` | [datadome](https://sursolver.com/solvers/datadome) |
| AWS WAF Challenge | `AwsChallengeCookie` | [aws-challenge](https://sursolver.com/solvers/aws-challenge) |
| AWS WAF CAPTCHA | `AwsCaptchaCookie` | [aws-captcha](https://sursolver.com/solvers/aws-captcha) |
| Akamai (`_abck`) | `AkamaiCookieProxyLess` | [akamai](https://sursolver.com/solvers/akamai) |
| Akamai SBSD | `AkamaiSbsdCookie` | [akamai-sbsd](https://sursolver.com/solvers/akamai-sbsd) |
| Akamai BMP (Android) | `AkamaiBmpTask` | [akamai-bmp](https://sursolver.com/solvers/akamai-bmp) |
| Kasada | `KasadaTokenProxyLess` | [kasada](https://sursolver.com/solvers/kasada) |
| Shape | `ShapeCookieProxyLess` | [shape](https://sursolver.com/solvers/shape) |
| Imperva (reese84 / utmvc) | `ImpervaCookie`, `ImpervaUtmvcCookie` | [imperva](https://sursolver.com/solvers/imperva) |
| Vercel Security Checkpoint | `VercelCookie` | [vercel](https://sursolver.com/solvers/vercel) |
| FriendlyCaptcha | `FriendlyCaptchaTokenProxyLess` | [friendlycaptcha](https://sursolver.com/solvers/friendlycaptcha) |
| MTCaptcha | `MtCaptchaTokenProxyLess` | [mtcaptcha](https://sursolver.com/solvers/mtcaptcha) |
| Prosopo | `ProsopoTokenProxyLess` | [prosopo](https://sursolver.com/solvers/prosopo) |
| CaptchaFox | `CaptchaFoxToken` | [captchafox](https://sursolver.com/solvers/captchafox) |
| Altcha | `AltchaTokenProxyLess` | [altcha](https://sursolver.com/solvers/altcha) |
| Lemin | `LeminTokenProxyLess` | [lemin](https://sursolver.com/solvers/lemin) |
| Castle (Android) | `CastleAndroidToken` | [castle-android](https://sursolver.com/solvers/castle-android) |
| Image to Text | `ImageToTextTask` | [image-to-text](https://sursolver.com/solvers/image-to-text) |

Each guide lists the fields to send and where to find them on the page. The live list is
`client.list_task_types()`; prices are `client.list_services()`.

## Errors

```python
from sursolver import NoSlotAvailableError, TaskFailedError

try:
    result = client.solve(task)
except NoSlotAvailableError:
    ...  # all your threads are busy: try again in a moment
except TaskFailedError:
    ...  # this captcha could not be solved; its charge is refunded
```

Other errors: `AuthenticationError` (wrong API key), `InvalidTaskError` (a field is missing or
wrong), `InsufficientBalanceError` (top up), `SolveTimeoutError` (no result in time).

## Links

- [Documentation](https://sursolver.com/docs) and [API reference](https://sursolver.com/docs/api)
- [Proxies guide](https://sursolver.com/docs/guides/proxies) and [error codes](https://sursolver.com/docs/guides/errors)
- [Pricing](https://sursolver.com/pricing)

## License

MIT
