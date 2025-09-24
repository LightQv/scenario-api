from app.core.settings import settings


def get_password_reset_template(username: str, reset_token: str) -> str:
    """
    Generate HTML template for reset password email

    Args:
        username: Username
        reset_token: Reset token

    Returns:
        Template HTML complet
    """
    return f"""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="X-UA-Compatible" content="ie=edge" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Abril+Fatface&family=Fira+Sans:wght@400;600;700&display=swap"
      rel="stylesheet"
    />
    <style>
      body {{
        margin: 0;
        padding: 0;
        background-color: #ffffff;
        font-family: 'Fira Sans', sans-serif;
      }}
      table {{
        border-collapse: collapse;
      }}
    </style>
  </head>
  <body>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="center" style="padding: 20px;">
          <table width="600" cellpadding="0" cellspacing="0" style="border:1px solid #ddd;border-radius:8px;">
            <tr>
              <td style="padding:20px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td align="center">
                      <h1 style="font-family:'Abril Fatface', serif;font-size:24px;font-weight:400;margin:0;">
                        Hey {username},
                      </h1>
                      <h2 style="font-size:16px;font-weight:400;margin-top:10px;">
                        You need to change your SCENARIO password?
                      </h2>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding:20px 0;">
                      <a href="{settings.FRONTEND_URL}/reset-password/{reset_token}" style="color:#eab208;text-decoration:none;display:inline-block;border:1px solid #eab208;border-radius:6px;padding:10px 20px;font-weight:600;">
                        RESET PASSWORD
                      </a>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding:10px 0;font-size:14px;color:#333;">
                      If you did not initiate this request, please contact us immediately at
                      <a href="mailto:{settings.MAIL_SERVICE}" style="color:#000;text-decoration:underline;">
                        {settings.MAIL_SERVICE}
                      </a>.
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:10px;font-size:14px;color:#333;">
                      Thank you,<br />The SCENARIO's Team.
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
    """
