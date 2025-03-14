-- CreateTable
CREATE TABLE "RiotAccount" (
    "id" SERIAL NOT NULL,
    "riotId" TEXT NOT NULL,
    "puuid" TEXT NOT NULL,
    "lastUpdate" TIMESTAMP(3),
    "profileIconURL" TEXT,
    "summonerLevel" INTEGER,
    "rankedInfo" JSONB,

    CONSTRAINT "RiotAccount_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Matches" (
    "matchId" TEXT NOT NULL,
    "data" JSONB NOT NULL,

    CONSTRAINT "Matches_pkey" PRIMARY KEY ("matchId")
);

-- CreateIndex
CREATE UNIQUE INDEX "RiotAccount_riotId_key" ON "RiotAccount"("riotId");

-- CreateIndex
CREATE UNIQUE INDEX "RiotAccount_puuid_key" ON "RiotAccount"("puuid");
