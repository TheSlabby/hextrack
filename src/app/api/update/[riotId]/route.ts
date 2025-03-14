import { PrismaClient } from "@prisma/client";
import { NextResponse } from "next/server";

const prisma = new PrismaClient();
const riot_api_key = process.env.RIOT_KEY;

export async function GET(request, { params }): Promise<NextResponse> {
    let { riotId }: { riotId: string } = await params;
    riotId = riotId.replace('-', '#');
    var puuid;

    const result = await prisma.riotAccount.findUnique({
        where: {
            riotId: riotId
        }
    });

    if (!result) {
        console.log('puuid not in database, fetching...');
        // we need to map riot id to puuid
        const seperatedId = riotId.split('#');
        const accountResponse = await fetch(
            `https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/${seperatedId[0]}/${seperatedId[1]}?api_key=${riot_api_key}`
        );

        if (accountResponse.ok) {
            const jsonResponse = await accountResponse.json();
            puuid = jsonResponse.puuid;

            await prisma.riotAccount.create({
                data: {
                    riotId,
                    puuid,
                    lastUpdate: new Date(),
                }
            });

            console.log("PUUID added:", puuid);
            
        } else {
            // COULDNT FIND PUUID
            return NextResponse.json("Couldn't get user data rip", {status: 400});
        }
    } else {
        // const resultJson = await result.json();
        puuid = result.puuid;
        console.log("already have puuid in database:");

        // make sure we're not spamming update
        const now = new Date();
        if (result?.lastUpdate && now.getTime() - new Date(result.lastUpdate).getTime() < 60000) {
            console.log('throttled user update (too soon)');
            return NextResponse.json({ message: "Can't update so soon!" }, { status: 200 });
        }
    }

    console.log("USING PUUID:", puuid);

    // now get matches for this user
    const matchResponse = await fetch(
        `https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/${puuid}/ids?api_key=${riot_api_key}`
    );
    const matchJson = await matchResponse.json();
    for (const matchId of matchJson) {
        const result = await prisma.matches.findUnique({
            where: {
                matchId: matchId
            }
        });

        if (!result) {
            console.log("adding new match:", matchId);
            const matchDataResponse = await fetch(
                `https://americas.api.riotgames.com/lol/match/v5/matches/${matchId}?api_key=${riot_api_key}`
            );
            const matchDataJson = await matchDataResponse.json();

            await prisma.matches.create({
                data: {
                    matchId,
                    data: matchDataJson,
                }
            });
        } else {
            console.log("already have match:", matchId);
        }
    }
    // update lastUpdate
    await prisma.riotAccount.update({
        where: { puuid },
        data: {
            lastUpdate: new Date(),
        }
    });

    return NextResponse.json(riotId);
    
}