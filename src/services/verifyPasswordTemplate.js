const { FRONTEND_URL, SMTP_USER } = process.env;

const verifyPasswordTemplate = (username, token) => {
  const html = `
  <!DOCTYPE html>
  <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <meta http-equiv="X-UA-Compatible" content="ie=edge" />
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
      <link
        href="https://fonts.googleapis.com/css2?family=Abril+Fatface&family=Fira+Sans:ital,wght@0,100;0,200;0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,100;1,200;1,300;1,400;1,500;1,600;1,700;1,800;1,900&display=swap"
        rel="stylesheet"
      />
    </head>
    <body
      style="
        margin: auto;
        width: 60%;
        background-color: #ffffff;
        padding: 5rem 8rem 5rem 8rem;
        border-radius: 1rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: 1rem;
        font-family: 'Fira Sans', sans-serif;
        --tw-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1),
          0 4px 6px -4px rgb(0 0 0 / 0.1);
        --tw-shadow-colored: 0 10px 15px -3px var(--tw-shadow-color),
          0 4px 6px -4px var(--tw-shadow-color);
        box-shadow: var(--tw-ring-offset-shadow, 0 0 #0000),
          var(--tw-ring-shadow, 0 0 #0000), var(--tw-shadow);
      "
    >
      <section style="text-align: center; padding-bottom: 0.5rem">
        <h1
          style="
            font-weight: 400;
            font-size: 1.875rem;
            font-family: 'Abril Fatface', serif;
          "
        >
          Hey ${username},
        </h1>
        <h2 style="font-size: 1rem; font-weight: 400">
          You need to change your DIWIT? password ?
        </h2>
      </section>
      <a
        href="${FRONTEND_URL}/reset-password/${token}"
        style="
          background-color: #adc178;
          border-color: #adc178;
          border-radius: 0.375rem;
          padding: 1rem 2rem 1rem 2rem;
          border-style: none;
          text-decoration: none;
          border-width: 1px;
          color: #f7f5f5;
          font-weight: 600;
          font-size: 1rem;
          margin-bottom: 0.5rem;
        "
        >RESET PASSWORD</a
      >
      <p style="text-align: center; font-size: 1rem">
        If you did not initiate this request, please contact us immediately at
        <a
          href="mailto:${SMTP_USER}"
          style="
            text-decoration-line: underline;
            text-underline-offset: 4px;
            text-decoration-thickness: 2px;
            text-decoration-color: #adc178;
            color: black;
          "
          >${SMTP_USER}</a
        >.
      </p>
      <p style="text-align: center; font-size: 1rem">
        Thank you,<br />The DIWIT? Team.
      </p>
      <img
        src="https://firebasestorage.googleapis.com/v0/b/scenario-f57d7.appspot.com/o/SCENARIO_b.png?alt=media&token=d85d80b8-3c0d-4214-a33f-accf0ed9f9ba"
        alt="logo"
        style="align-self: center; height: 2rem"
      />
    </body>
  </html>
  `;

  return html;
};

module.exports = { verifyPasswordTemplate };
