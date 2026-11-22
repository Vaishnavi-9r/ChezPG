export type City = {
  id: number;
  name: string;
  state: string;
  country: string;
};

export type Area = {
  id: number;
  city_id: number;
  name: string;
};

export type NearbyPlace = {
  id: number;
  city_id: number;
  area_id: number | null;
  name: string;
  category: string;
  address: string | null;
  latitude: number;
  longitude: number;
};

export type PGListing = {
  id: number;
  city_id: number;
  area_id: number;
  name: string;
  description: string | null;
  address: string;
  stay_type: "men" | "women" | "co_living";
  monthly_rent: number | string;
  security_deposit: number | string | null;
  electricity_included: boolean;
  food_available: boolean;
  contact_phone: string | null;
  verification_status: string;
  area_name: string | null;
  total_available_beds: number;
  average_rating: number | string | null;
  published_review_count: number;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const configuredUrl = process.env.EXPO_PUBLIC_API_URL?.trim();
export const API_BASE_URL = (configuredUrl || "http://localhost:8000/api/v1").replace(/\/+$/, "");

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(
      `Could not connect to ${API_BASE_URL}. Check the backend address and that FastAPI is running.`,
    );
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (
        body &&
        typeof body === "object" &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        detail = body.detail;
      }
    } catch {
      // Keep the HTTP status message if the server response is not JSON.
    }
    throw new ApiError(detail, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The server returned an invalid response.");
  }
}

export const api = {
  getCities: () => request<City[]>("/cities"),
  getAreas: (cityId: number) => request<Area[]>(`/cities/${cityId}/areas`),
  searchPGs: (params: URLSearchParams) => request<PGListing[]>(`/pgs?${params.toString()}`),
  searchNearbyPlaces: (cityId: number, query: string) =>
    request<NearbyPlace[]>(
      `/nearby-places?city_id=${cityId}&q=${encodeURIComponent(query)}&limit=10`,
    ),
};
