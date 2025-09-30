import os
import requests
from rag_pipeline import generate_response_with_context
from session_store import clear_session

def get_function_definitions():
    """Define all available tools/functions for the AI"""
    return [
        {
            "type": "function",
            "function": {
                "name": "clear_conversation",
                "description": "Clear the current conversation history and start a fresh session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string", 
                            "description": "Why the conversation is being cleared"
                        }
                    },
                    "required": [],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function", 
            "function": {
                "name": "find_coffee_shops",
                "description": "Find coffee shops in a specific city using external API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "The city to search for coffee shops in"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 5
                        },
                        "coffee_type": {
                            "type": "string",
                            "description": "Type of coffee shop preference",
                            "enum": ["specialty", "cafe", "espresso_bar", "roastery", "any"]
                        }
                    },
                    "required": ["city"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_coffee_knowledge",
                "description": "Search through coffee knowledge base for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant coffee information"
                        },
                        "top_k": {
                            "type": "integer", 
                            "description": "Number of top results to return",
                            "default": 3
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculate_brew_ratio",
                "description": "Calculate coffee to water ratio and provide brewing advice",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coffee_amount": {
                            "type": "number",
                            "description": "Amount of coffee in grams"
                        },
                        "water_amount": {
                            "type": "number", 
                            "description": "Amount of water in grams or ml"
                        },
                        "brew_method": {
                            "type": "string",
                            "description": "Brewing method being used",
                            "enum": ["pour_over", "french_press", "espresso", "aeropress", "cold_brew", "moka_pot"]
                        }
                    },
                    "required": ["coffee_amount", "water_amount"],
                    "additionalProperties": False
                }
            }
        }
    ]

# --- Function implementations ---
def clear_conversation_fn(session_id, reason=None):
    """Clear conversation function implementation using actual session clearing"""
    clear_session(session_id)
    return {
        "success": True,
        "message": f"Conversation cleared. Reason: {reason if reason else 'User requested to start fresh'}",
        "session_id": session_id
    }

def find_coffee_shops_fn(city, limit=5, coffee_type="any"):
    try:
        api_key = os.getenv("PLACE_SEARCH_API_KEY")
        
        if not api_key:
            return {"error": "TomTom API key not configured", "places": []}

        # TomTom Search API - CORRECT ENDPOINT
        base_url = "https://api.tomtom.com/search/2/poiSearch/.json"
        
        # Build query - TomTom needs more specific parameters
        params = {
            "query": "coffee",  # Changed from coffee shops to just coffee
            "limit": min(limit, 100),
            "countrySet": "US,CA,GB,AU",  # Important: Specify countries
            "key": api_key
        }

        # For better results, we should geocode the city first
        geocode_url = "https://api.tomtom.com/search/2/geocode/.json"
        geo_params = {
            "query": city,
            "key": api_key
        }
        
        # First, get coordinates for the city
        geo_response = requests.get(geocode_url, params=geo_params, timeout=10)
        if geo_response.status_code == 200:
            geo_data = geo_response.json()
            if geo_data.get("results"):
                # Use the first result's coordinates
                lat = geo_data["results"][0]["position"]["lat"]
                lon = geo_data["results"][0]["position"]["lon"]
                
                # Update search to use coordinates
                params["lat"] = lat
                params["lon"] = lon
                params["radius"] = 20000  # 20km radius

        response = requests.get(base_url, params=params, timeout=10)
        
        print(f"DEBUG: TomTom Status: {response.status_code}")
        print(f"DEBUG: TomTom Response: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            places = []
            
            for result in data.get("results", [])[:limit]:
                poi = result.get("poi", {})
                address = result.get("address", {})
                
                places.append({
                    "name": poi.get("name", "Unknown"),
                    "address": address.get("freeformAddress", "Address not available"),
                    "distance": f"{result.get('dist', 0):.1f} km",
                    "category": ", ".join(poi.get("categories", [])),
                    "phone": poi.get("phone", "Not available")
                })
                
            return {
                "city": city,
                "places_found": len(places),
                "places": places
            }
        else:
            return {
                "error": f"TomTom API error: {response.status_code} - {response.text}",
                "places": []
            }
            
    except Exception as e:
        return {
            "error": f"TomTom API failed: {str(e)}",
            "places": []
        }

def search_coffee_knowledge_fn(query, top_k=3):
    """Search coffee knowledge base"""
    rag_response = generate_response_with_context(query, top_k=top_k)
    return {
        "answer": rag_response.get("answer", "No information found"),
        "references": rag_response.get("references", []),
        "query": query
    }

def calculate_brew_ratio_fn(coffee_amount, water_amount, brew_method=None):
    """Calculate coffee to water ratio"""
    ratio = water_amount / coffee_amount
    advice = f"Brew ratio: 1:{ratio:.1f} (coffee:water)"
    
    if brew_method:
        advice += f" for {brew_method.replace('_', ' ').title()}"
    
    # Add method-specific advice
    if brew_method == "espresso" and 1.5 <= ratio <= 2.5:
        advice += " - Good espresso ratio!"
    elif brew_method == "pour_over" and 15 <= ratio <= 17:
        advice += " - Ideal pour over range!"
    elif brew_method == "french_press" and 12 <= ratio <= 15:
        advice += " - Perfect French press ratio!"
    
    return {
        "coffee_amount": coffee_amount,
        "water_amount": water_amount,
        "ratio": round(ratio, 1),
        "advice": advice
    }

# Map function names to implementations
FUNCTION_MAP = {
    "clear_conversation": clear_conversation_fn,
    "find_coffee_shops": find_coffee_shops_fn,
    "search_coffee_knowledge": search_coffee_knowledge_fn,
    "calculate_brew_ratio": calculate_brew_ratio_fn
}

def execute_function(function_name, function_args, session_id=None):
    """Execute a function by name with provided arguments"""
    if function_name in FUNCTION_MAP:

        if function_name == "clear_conversation" and session_id:
            return FUNCTION_MAP[function_name](session_id, **function_args)
        else:
            return FUNCTION_MAP[function_name](**function_args)
    else:
        return {"error": f"Function {function_name} not found"}