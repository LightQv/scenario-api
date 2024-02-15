require("dotenv").config();
const nodemailer = require("nodemailer");
const { verifyPasswordTemplate } = require("./verifyPasswordTemplate");

const { SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD } = process.env;

const smtpConfig = {
  host: SMTP_HOST,
  port: SMTP_PORT,
  secure: false,
  auth: {
    user: SMTP_USER,
    pass: SMTP_PASSWORD,
  },
};

const transporter = nodemailer.createTransport(smtpConfig);

const sendForgottenPassword = (req, res) => {
  const messageTemplate = verifyPasswordTemplate(
    req.user.username,
    req.user.passwordToken
  );
  const mailOptions = {
    from: SMTP_USER,
    to: req.user.email,
    subject: `${req.user.username}, have you forgot your password ?`,
    text: "Click here to create a new password !",
    html: messageTemplate,
  };

  transporter.sendMail(mailOptions, (err, info) => {
    console.warn(info);
    if (err) {
      console.error(err);
      res.sendStatus(500);
    } else res.sendStatus(200);
  });
};

module.exports = { sendForgottenPassword };
