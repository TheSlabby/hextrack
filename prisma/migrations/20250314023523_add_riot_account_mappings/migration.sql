-- CreateTable
CREATE TABLE "RiotAccount" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "riotId" TEXT NOT NULL,
    "puuid" TEXT NOT NULL
);

-- CreateIndex
CREATE UNIQUE INDEX "RiotAccount_riotId_key" ON "RiotAccount"("riotId");

-- CreateIndex
CREATE UNIQUE INDEX "RiotAccount_puuid_key" ON "RiotAccount"("puuid");
