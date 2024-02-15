const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const getUser = async (req, res) => {
  try {
    const userData = await prisma.user.findUnique({
      select: {
        username: true,
        email: true,
        profileBanner: true,
      },
      where: {
        id: req.params.id,
      },
    });
    if (!userData) {
      throw new Error();
    }
    res.send(userData);
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

const getUserBanner = async (req, res) => {
  try {
    const userBanner = await prisma.user.findUnique({
      select: {
        profileBanner: true,
      },
      where: {
        id: req.params.id,
      },
    });
    if (!userBanner) {
      throw new Error();
    }
    res.send(userBanner);
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

const addUser = async (req, res) => {
  try {
    const isCreate = await prisma.user.create({
      data: {
        username: req.body.username,
        email: req.body.email,
        hashedPassword: req.body.hashedPassword,
      },
    });
    if (!isCreate) {
      throw new Error();
    }
    res.sendStatus(204);
  } catch (err) {
    console.error(err);
    if (err.code === "P2002") {
      res.sendStatus(400);
    } else res.sendStatus(500);
  }
};

const editUser = async (req, res) => {
  try {
    const isUpdated = await prisma.user.update({
      where: {
        id: req.params.id,
      },
      data: {
        username: req.body.username,
        email: req.body.email,
        hashedPassword: req.body.hashedPassword,
      },
    });
    if (isUpdated) {
      res.sendStatus(204);
    } else {
      res.status(404).send("User not found");
    }
  } catch (err) {
    console.error(err);
    if (err.code === "P2002") {
      res.sendStatus(400);
    } else res.sendStatus(500);
  }
};

const editUserMail = async (req, res) => {
  try {
    const isMailUpdated = await prisma.user.update({
      where: {
        id: req.params.id,
      },
      data: {
        email: req.body.email,
      },
    });
    if (isMailUpdated) {
      res.sendStatus(204);
    } else {
      res.status(404).send("User not found");
    }
  } catch (err) {
    if (err) {
      console.error(err);
      res.sendStatus(500);
    }
  }
};

const editUserPw = async (req, res) => {
  req.body.passwordToken = null;
  try {
    const isPwModified = await prisma.user.update({
      where: {
        id: req.params.id || req.user.id,
      },
      data: {
        hashedPassword: req.body.hashedPassword,
        passwordToken: req.body.passwordToken,
      },
    });
    if (isPwModified) {
      res.sendStatus(204);
    } else {
      res.status(404).send("User not found");
    }
  } catch (err) {
    if (err) {
      console.error(err);
      res.sendStatus(500);
    }
  }
};

const editUserBanner = async (req, res) => {
  try {
    const isBannerEdited = await prisma.user.update({
      where: {
        id: req.params.id,
      },
      data: {
        profileBanner: req.body.bannerLink,
      },
    });
    if (isBannerEdited) {
      res.sendStatus(204);
    } else {
      res.status(404).send("User not found");
    }
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

const deleteUser = async (req, res) => {
  try {
    const isDelete = await prisma.user.delete({
      where: {
        id: req.params.id,
      },
    });
    if (isDelete) {
      res.sendStatus(204);
    } else res.status(404).send("User not found");
  } catch (err) {
    console.log(err);
    if (err) res.sendStatus(500);
  }
};

module.exports = {
  getUser,
  getUserBanner,
  addUser,
  editUser,
  editUserMail,
  editUserPw,
  editUserBanner,
  deleteUser,
};
