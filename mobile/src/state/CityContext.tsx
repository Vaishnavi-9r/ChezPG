import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";
import type { City } from "../lib/api";

const STORAGE_KEY = "@chezpg/selected-city";

type CityState = {
  city: City | null;
  isTemporary: boolean;
  setCity: (city: City, temporary?: boolean) => void;
};

const CityContext = createContext<CityState | null>(null);

export function CityProvider({ children }: PropsWithChildren) {
  const [city, updateCity] = useState<City | null>(null);
  const [isTemporary, setIsTemporary] = useState(false);

  useEffect(() => {
    let mounted = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((savedCity) => {
        if (!mounted || !savedCity) return;
        const parsed: { city: City; temporary: boolean } = JSON.parse(savedCity);
        updateCity(parsed.city);
        setIsTemporary(parsed.temporary);
      })
      .catch(() => {
        console.warn("Could not restore the saved city preference.");
      });
    return () => {
      mounted = false;
    };
  }, []);

  function setCity(nextCity: City, temporary = false) {
    updateCity(nextCity);
    setIsTemporary(temporary);
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ city: nextCity, temporary })).catch(() => {
      console.warn("Could not save the city preference; the in-memory selection is still active.");
    });
  }

  const value = useMemo(
    () => ({ city, isTemporary, setCity }),
    [city, isTemporary],
  );
  return <CityContext.Provider value={value}>{children}</CityContext.Provider>;
}

export function useCity(): CityState {
  const context = useContext(CityContext);
  if (!context) throw new Error("useCity must be used within CityProvider");
  return context;
}
