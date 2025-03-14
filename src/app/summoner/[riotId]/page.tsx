'use client';

import { use, useEffect, useState } from "react";

export default function SummonerPage({ params }) {
    const [puuid, setPuuid] = useState();
    const [invalidUser, setInvalidUser] = useState(false);
    const [stats, setStats] = useState();

    const { riotId }: { riotId: string } = use(params);

    
    useEffect(() => {
        const update = async () => {
            const result = await fetch(`/api/update/${riotId}`);
            if (!result.ok) {
                setInvalidUser(true);
            } else {
                const result = await fetch(`/api/stats/${riotId}`);
                const json = await result.json();
                setStats(json);
            }
        }


        // run update
        console.log('updating user...');
        update();
    }, []);

    if (invalidUser) return (
        <div>
            <p className="mt-10 text-3xl text-red-500 text-center font-bold">
                Invalid user: <span className="font-light">{riotId}</span>
            </p>
        </div>
    )

    return (
        <div>
            <p>{riotId}</p>
            <p>{JSON.stringify(stats)}</p>
        </div>
    )
}