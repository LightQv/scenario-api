const { PrismaClient } = require("@prisma/client");
const { v4: uuidv4 } = require("uuid");

const prisma = new PrismaClient();

const getUserByEmailMiddleware = async (req, res, next) => {
  try {
    const userByEmail = await prisma.user.findUnique({
      where: {
        email: req.body.email,
      },
    });
    if (userByEmail) {
      req.user = userByEmail;
      next();
    } else res.sendStatus(401);
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

// Generate a Token before sending it to user's email
const generatePasswordToken = async (req, res, next) => {
  // Add a temporary token to request a new password
  req.user.passwordToken = uuidv4();

  try {
    const updatePasswordToken = await prisma.user.update({
      where: {
        id: req.user.id,
      },
      data: {
        passwordToken: req.user.passwordToken,
      },
    });
    if (updatePasswordToken) {
      next();
    } else throw new Error();
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

// Verify if a User got the Password Token
const verifyPasswordToken = async (req, res, next) => {
  try {
    const verifiedToken = await prisma.user.findFirst({
      where: {
        passwordToken: req.body.passwordToken.toString(),
      },
    });
    if (verifiedToken) {
      req.user = verifiedToken;
      next();
    } else res.sendStatus(200);
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

module.exports = {
  getUserByEmailMiddleware,
  generatePasswordToken,
  verifyPasswordToken,
};
