/*
  Warnings:

  - The primary key for the `User` table will be changed. If it partially fails, the table could be left without primary key constraint.
  - The primary key for the `Watchlist` table will be changed. If it partially fails, the table could be left without primary key constraint.
  - You are about to drop the column `createdAt` on the `Watchlist` table. All the data in the column will be lost.
  - You are about to drop the column `updateAt` on the `Watchlist` table. All the data in the column will be lost.
  - You are about to drop the `Movie` table. If the table is not empty, all the data it contains will be lost.
  - You are about to drop the `TvShow` table. If the table is not empty, all the data it contains will be lost.

*/
-- DropForeignKey
ALTER TABLE "Movie" DROP CONSTRAINT "Movie_watchlistId_fkey";

-- DropForeignKey
ALTER TABLE "TvShow" DROP CONSTRAINT "TvShow_watchlistId_fkey";

-- DropForeignKey
ALTER TABLE "Watchlist" DROP CONSTRAINT "Watchlist_authorId_fkey";

-- AlterTable
ALTER TABLE "User" DROP CONSTRAINT "User_pkey",
ALTER COLUMN "id" DROP DEFAULT,
ALTER COLUMN "id" SET DATA TYPE TEXT,
ADD CONSTRAINT "User_pkey" PRIMARY KEY ("id");
DROP SEQUENCE "User_id_seq";

-- AlterTable
ALTER TABLE "Watchlist" DROP CONSTRAINT "Watchlist_pkey",
DROP COLUMN "createdAt",
DROP COLUMN "updateAt",
ALTER COLUMN "id" DROP DEFAULT,
ALTER COLUMN "id" SET DATA TYPE TEXT,
ALTER COLUMN "authorId" SET DATA TYPE TEXT,
ADD CONSTRAINT "Watchlist_pkey" PRIMARY KEY ("id");
DROP SEQUENCE "Watchlist_id_seq";

-- DropTable
DROP TABLE "Movie";

-- DropTable
DROP TABLE "TvShow";

-- CreateTable
CREATE TABLE "Media" (
    "id" TEXT NOT NULL,
    "dataId" INTEGER NOT NULL,
    "genre" INTEGER[],
    "poster_path" TEXT NOT NULL,
    "release_date" TEXT NOT NULL,
    "runtime" INTEGER NOT NULL,
    "title" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "watchlistId" TEXT NOT NULL,

    CONSTRAINT "Media_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "View" (
    "id" TEXT NOT NULL,
    "dataId" INTEGER NOT NULL,
    "genre" INTEGER[],
    "poster_path" TEXT NOT NULL,
    "release_date" TEXT NOT NULL,
    "release_year" TEXT NOT NULL,
    "runtime" INTEGER NOT NULL,
    "title" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "viewerId" TEXT NOT NULL,

    CONSTRAINT "View_pkey" PRIMARY KEY ("id")
);

-- AddForeignKey
ALTER TABLE "Watchlist" ADD CONSTRAINT "Watchlist_authorId_fkey" FOREIGN KEY ("authorId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Media" ADD CONSTRAINT "Media_watchlistId_fkey" FOREIGN KEY ("watchlistId") REFERENCES "Watchlist"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "View" ADD CONSTRAINT "View_viewerId_fkey" FOREIGN KEY ("viewerId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;
