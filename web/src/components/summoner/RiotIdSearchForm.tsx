import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import { DEFAULT_REGION, parseRiotIdInput, summonerParams } from "@/lib/riotId";

export interface RiotIdSearchFormProps {
  defaultValue?: string;
  region?: string;
  className?: string;
}

/** Inline "Name#TAG" search used by the not-found and error states. */
export function RiotIdSearchForm({ defaultValue = "", region = DEFAULT_REGION, className }: RiotIdSearchFormProps) {
  const navigate = useNavigate();
  const [value, setValue] = useState(defaultValue);
  const [invalid, setInvalid] = useState(false);
  const inputId = useId();
  const errorId = `${inputId}-error`;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = parseRiotIdInput(value);
    if (!parsed) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    void navigate({
      to: "/summoner/$region/$riotId",
      params: summonerParams(parsed.gameName, parsed.tagLine, region),
    });
  };

  return (
    <form onSubmit={submit} className={cn("flex w-full max-w-md flex-col gap-1.5", className)} role="search">
      <label htmlFor={inputId} className="sr-only">
        Riot ID
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-gold" aria-hidden="true" />
          <Input
            id={inputId}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              if (invalid) setInvalid(false);
            }}
            placeholder="Name#TAG"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? errorId : undefined}
            className="pl-9"
          />
        </div>
        <Button type="submit" className="h-10">
          Search
        </Button>
      </div>
      {invalid ? (
        <p id={errorId} className="text-left text-xs text-loss">
          Use the full Riot ID with its tag, like Hexwalker#NA1.
        </p>
      ) : null}
    </form>
  );
}
