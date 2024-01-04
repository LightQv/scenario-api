const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();

const viewByUser = async (req, res) => {
  try {
    const usersViews = await prisma.view.findMany({
      where: {
        viewerId: req.params.id,
        AND: {
          type: req.params.type,
        },
      },
    });

    if (usersViews) {
      res.send(usersViews);
    } else if (usersViews === null) {
      res.send({
        views: [],
      });
    } else throw new Error();
  } catch (err) {
    console.error(err);
    res.sendStatus(500);
  }
};

const viewRuntimeByUser = async (req, res) => {
  try {
    const viewsRuntime = await prisma.view.findMany({
      where: {
        viewerId: req.params.id,
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
        dataId: req.body.dataId,
        poster_path: req.body.poster_path,
        release_date: req.body.release_date,
        runtime: req.body.runtime,
        title: req.body.title,
        type: req.body.type,
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

module.exports = { viewByUser, viewRuntimeByUser, addView, deleteView };
