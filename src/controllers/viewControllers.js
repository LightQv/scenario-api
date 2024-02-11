const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const viewByUser = async (req, res) => {
  try {
    const usersViews = await prisma.view.findMany({
      where: {
        viewerId: req.params.id,
      },
    });

    if (usersViews) {
      res.send(usersViews);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const viewByType = async (req, res) => {
  try {
    const usersViewsByType = await prisma.view.findMany({
      where: {
        viewerId: req.params.id,
        AND: {
          media_type: req.params.type,
          genre_ids: {
            has: Number(req.query.genre),
          },
        },
      },
    });

    if (usersViewsByType) {
      res.send(usersViewsByType);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const countViewByType = async (req, res) => {
  try {
    const countUserViewByType = await prisma.view.groupBy({
      by: ["media_type"],
      where: {
        viewerId: req.params.id,
        AND: {
          media_type: req.params.type,
        },
      },
      _count: true,
    });

    if (countUserViewByType) {
      res.send(countUserViewByType);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const countViewByYear = async (req, res) => {
  try {
    const countUserViewByYear = await prisma.view.groupBy({
      by: ["release_year"],
      where: {
        viewerId: req.params.id,
        AND: {
          media_type: req.params.type,
        },
      },
      _count: true,
      orderBy: {
        release_year: "asc",
      },
    });

    if (countUserViewByYear) {
      res.send(countUserViewByYear);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const runtimeViewByUser = async (req, res) => {
  try {
    const viewsRuntime = await prisma.view.findMany({
      where: {
        viewerId: req.params.id,
        AND: {
          media_type: req.params.type,
        },
      },
      select: {
        runtime: true,
      },
    });
    if (viewsRuntime) {
      res.send(viewsRuntime);
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const addView = async (req, res) => {
  try {
    const isViewed = await prisma.view.create({
      data: {
        tmdb_id: req.body.tmdb_id,
        genre_ids: req.body.genre_ids,
        poster_path: req.body.poster_path,
        backdrop_path: req.body.backdrop_path,
        release_date: req.body.release_date,
        release_year: req.body.release_year,
        runtime: req.body.runtime,
        title: req.body.title,
        media_type: req.body.media_type,
        viewerId: req.body.viewerId,
      },
    });
    if (!isViewed) {
      throw new Error();
    }
    res.sendStatus(204);
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const deleteView = async (req, res) => {
  try {
    const isDelete = await prisma.view.delete({
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
  viewByUser,
  viewByType,
  countViewByType,
  countViewByYear,
  runtimeViewByUser,
  addView,
  deleteView,
};
