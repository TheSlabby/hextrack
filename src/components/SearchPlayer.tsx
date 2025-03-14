'use client';

import { useRouter } from "next/navigation";
import { useState } from "react";
import Button from "./Button";

export default function SearchPlayer() {
    const router = useRouter();

    const [searchId, setSearchId] = useState('');
    const [errorMessage, setErrorMessage] = useState('');
    const searchPlayer = () => {
        const splitId = searchId.split('#');
        const formatted = searchId.replace('#', '-');
        if (splitId.length == 2) {
          router.push('/summoner/' + formatted)
        } else {
          setErrorMessage('Invalid search format (example: TheSlab#333)');
        }
      }

      return (
        <div className="flex flex-col">
            <input value={searchId} onChange={e => setSearchId(e.target.value)} className="mt-3 w-3/4 mx-auto placeholder:text-slate-500 text-slate-200 border border-slate-200 rounded-lg px-3 py-2 transition duration-300 ease focus:outline-none focus:border-slate-400 hover:border-slate-300 shadow-sm focus:shadow" placeholder="TheSlab#333" />
            <Button className="bg-blue-800 w-3/5 mx-auto mt-3" onClick={searchPlayer}>Search</Button>
            <p className="text-sm font-light text-red-400 text-center mt-2">{errorMessage}</p>
        </div>
        
      )
}