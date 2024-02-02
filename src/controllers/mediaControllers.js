const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const addMedia = async (req, res) => {
  try {
    const isCreated = await prisma.media.create({
      data: {
        tmdb_id: req.body.tmdb_id,
        genre_ids: req.body.genre_ids,
        poster_path: req.body.poster_path,
        backdrop_path: req.body.backdrop_path,
        release_date: req.body.release_date,
        runtime: req.body.runtime,
        title: req.body.title,
        media_type: req.body.media_type,
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

const editMedia = async (req, res) => {
  try {
    const isEdited = await prisma.media.update({
      data: {
        watchlistId: req.body.watchlistId,
      },
      where: {
        id: req.params.id,
      },
    });
    if (!isEdited) {
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
  editMedia,
  deleteMedia,
};
