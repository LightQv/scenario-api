const { PrismaClient } = require("@prisma/client");

const prisma = new PrismaClient();
const { users } = require("./data");

async function main() {
  await prisma.user.deleteMany();
  await prisma.user.createMany({
    data: users,
  });
}

main()
  .catch((e) => {
    console.warn(e);
    process.exit(1);
  })
  .finally(() => {
    prisma.$disconnect();
  });
