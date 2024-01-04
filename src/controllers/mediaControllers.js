const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const addMedia = async (req, res) => {
  try {
    const isCreated = await prisma.media.create({
      data: {
        dataId: req.body.dataId,
        poster_path: req.body.poster_path,
        release_date: req.body.release_date,
        runtime: req.body.runtime,
        title: req.body.title,
        type: req.body.type,
        watchlistId: req.body.watchlistId,
      },
    });
    if (!isCreated) {
      throw new Error();
    }
    res.sendStatus(204);
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const deleteMedia = async (req, res) => {
  try {
    const isDelete = await prisma.media.delete({
      where: {
        id: req.params.id,
      },
    });
    if (isDelete) {
      res.sendStatus(204);
    } else res.status(404).send("View not found");
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

module.exports = {
  addMedia,
  deleteMedia,
};
