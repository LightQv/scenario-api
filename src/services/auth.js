const argon2 = require("argon2");
const jwt = require("jsonwebtoken");

const { JWT_SECRET, JWT_TIMING, NODE_ENV, SAME_SITE } = process.env;

const hashingOptions = {
  type: argon2.argon2id,
  memoryCost: 2 ** 16,
  timeCost: 5,
  parallelism: 1,
};

// Hash clear password submited at registration & delete them from the request
const hashPassword = (req, res, next) => {
  argon2
    .hash(req.body.password, hashingOptions)
    .then((hashedPassword) => {
      req.body.hashedPassword = hashedPassword;
      delete req.body.password;
      delete req.body.confirmPassword;
      next();
    })
    .catch((err) => {
      console.error(err);
      res.status(500).send("Something went wrong");
    });
};

const verifyPassword = (req, res) => {
  argon2
    .verify(req.user.hashedPassword, req.body.password, hashingOptions)
    .then((isVerified) => {
      if (isVerified) {
        const token = jwt.sign(
          {
            sub: req.user,
          },
          JWT_SECRET,
          {
            expiresIn: JWT_TIMING,
          }
        );

        delete req.body.password;
        delete req.user?.hashedPassword;
        delete req.user?.passwordToken;
        delete req.user?.profileBanner;

        // Put token in cookie and send user's safe data
        res
          .cookie("access_token", token, {
            httpOnly: true,
            secure: NODE_ENV === "production",
            maxAge: 30 * 24 * 60 * 60 * 1000,
            sameSite: SAME_SITE,
          })
          .send(req.user);
      } else res.sendStatus(401);
    })
    .catch((err) => {
      console.error(err);
      res.sendStatus(500);
    });
};

const verifyToken = (req, res, next) => {
  try {
    // Get Token from cookies
    const token = req.cookies.access_token;

    if (!token) return res.sendStatus(403);

    // Verify Token with JWT_SECRET
    req.payloads = jwt.verify(token, JWT_SECRET);
    return next();
  } catch (err) {
    console.error(err);
    return res.sendStatus(403);
  }
};

const logout = (req, res) => {
  res
    .clearCookie("access_token", req.cookies.access_token, {
      httpOnly: true,
      secure: NODE_ENV === "production",
      maxAge: 30 * 24 * 60 * 60 * 1000,
      sameSite: SAME_SITE,
    })
    .sendStatus(200);
};

module.exports = { hashPassword, verifyPassword, verifyToken, logout };
