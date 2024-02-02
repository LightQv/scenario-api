const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const watchlistByUser = async (req, res) => {
  try {
    const usersWatchlists = await prisma.watchlist.findMany({
      where: {
        authorId: req.params.id,
      },
      select: {
        id: true,
        title: true,
        authorId: true,
        _count: {
          select: {
            medias: true,
          },
        },
        medias: {
          select: {
            id: true,
            tmdb_id: true,
          },
        },
      },
    });
    if (usersWatchlists) {
      res.send(usersWatchlists);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const watchlistDetails = async (req, res) => {
  try {
    const watchlist = await prisma.watchlist.findUnique({
      where: {
        id: req.params.id,
      },
      select: {
        title: true,
        medias: true,
        _count: {
          select: {
            medias: true,
          },
        },
      },
    });
    if (watchlist) {
      res.send(watchlist);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const addWatchlist = async (req, res) => {
  try {
    const isCreated = await prisma.watchlist.create({
      data: {
        title: req.body.title,
        authorId: req.body.authorId,
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

const editWatchlist = async (req, res) => {
  try {
    const isEdited = await prisma.watchlist.update({
      data: {
        title: req.body.title,
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

const deleteWatchlist = async (req, res) => {
  try {
    const isDelete = await prisma.watchlist.delete({
      where: {
        id: req.params.id,
      },
    });
    if (isDelete) {
      res.sendStatus(204);
    } else res.status(404).send("Watchlist not found");
  } catch (err) {
    if (err) res.sendStatus(500);
  }
};

module.exports = {
  watchlistByUser,
  watchlistDetails,
  addWatchlist,
  editWatchlist,
  deleteWatchlist,
};
