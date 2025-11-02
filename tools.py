import os
import json
import logging
import requests
from session_store import clear_session, get_session

# --- Function Definitions for AI ---
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
                        "reason": {"type": "string", "description": "Why the conversation is being cleared"}
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
                "description": "Find up to 3 coffee shops near a specific city using OpenStreetMap APIs",  
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "The city to search for coffee shops in"},
                        "coffee_type": {
                            "type": "string",
                            "description": "Type of coffee shop preference",
                            "enum": ["specialty", "cafe", "espresso_bar", "roastery", "any"],
                            "default": "any"
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
                "name": "calculate_brew_ratio",
                "description": "Calculate coffee to water ratio and provide brewing advice",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coffee_amount": {"type": "number", "description": "Amount of coffee in grams"},
                        "water_amount": {"type": "number", "description": "Amount of water in grams or ml"},
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

# --- Function Implementations ---
def clear_conversation_fn(session_id, reason=None):
    clear_session(session_id)
    fresh_session = get_session(session_id)
    return {
        "success": True,
        "message": f"Conversation cleared. Reason: {reason or 'User requested to start fresh'}",
        "session_id": session_id,
        "refresh_required": True,
        "cleared_session": {
            "history": fresh_session.get("history", []),
            "summary": fresh_session.get("summary", ""),
            "system_prompt": fresh_session.get("system_prompt", ""),
            "message_count": len([msg for msg in fresh_session.get("history", []) if msg["role"] in ["user", "assistant"]])
        }
    }

def find_coffee_shops_fn(city, coffee_type="any"):
    try:
        osm_result = try_osm_search(city, coffee_type)
        if osm_result and osm_result.get("places"):
            return osm_result
            
        return {
            "error": "Live search unavailable",
            "places": [],
            "fallback_used": True
        }

    except Exception as e:
        logging.error(f"All search methods failed: {str(e)}")
        return {"error": f"Search failed: {str(e)}", "places": []}

def try_osm_search(city, coffee_type):
    """Fallback to OpenStreetMap"""
    try:
        logging.info(f" Falling back to OpenStreetMap for {city}")
        
        
        geo_url = "https://nominatim.openstreetmap.org/search"
        geo_params = {
            "q": city,  
            "format": "json",
            "limit": 1
        }
        
        geo_response = requests.get(geo_url, params=geo_params, timeout=10, 
                                  headers={'User-Agent': 'CoffeeChatApp/1.0'})
        
        if geo_response.status_code != 200:
            return None
            
        geo_data = geo_response.json()
        if not geo_data:
            return None
            
        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]
        
        
        found_location = geo_data[0].get("display_name", "Unknown location")
        logging.info(f"OSM geocoded '{city}' to: {found_location}")
        
        
        overpass_query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="cafe"](around:5000,{lat},{lon});
          node["shop"="coffee"](around:5000,{lat},{lon});
          node["amenity"="coffee_shop"](around:5000,{lat},{lon});
        );
        out body;
        """
        
        overpass_url = "https://overpass-api.de/api/interpreter"
        response = requests.post(overpass_url, data={"data": overpass_query}, timeout=25)
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        places = []
        
        for element in data.get("elements", [])[:3]:
            tags = element.get("tags", {})
            name = tags.get("name", "Coffee Shop")
            address_parts = []
            if tags.get("addr:street"):
                address_parts.append(tags.get("addr:street"))
            if tags.get("addr:housenumber"):
                address_parts.append(tags.get("addr:housenumber"))
            if tags.get("addr:city"):
                address_parts.append(tags.get("addr:city"))
            if tags.get("addr:country"):
                address_parts.append(tags.get("addr:country"))
                
            address = ", ".join(address_parts) if address_parts else "Address not available"
            
            places.append({
                "name": name,
                "address": address,
                "type": tags.get("amenity", "cafe"),
                "source": "openstreetmap"
            })
        
        return {
            "city": city, 
            "places_found": len(places), 
            "places": places, 
            "source": "openstreetmap",
            "actual_location": found_location 
        }
        
    except Exception as e:
        logging.error(f"OSM fallback also failed: {str(e)}")
        return None

def calculate_brew_ratio_fn(coffee_amount, water_amount, brew_method=None):
    ratio = water_amount / coffee_amount
    advice = f"Brew ratio: 1:{ratio:.1f} (coffee:water)"
    if brew_method:
        advice += f" for {brew_method.replace('_', ' ').title()}"
    if brew_method == "espresso" and 1.5 <= ratio <= 2.5:
        advice += " - Good espresso ratio!"
    elif brew_method == "pour_over" and 15 <= ratio <= 17:
        advice += " - Ideal pour over range!"
    elif brew_method == "french_press" and 12 <= ratio <= 15:
        advice += " - Perfect French press ratio!"
    return {"coffee_amount": coffee_amount, "water_amount": water_amount, "ratio": round(ratio,1), "advice": advice}

# --- Map function names to implementations ---
FUNCTION_MAP = {
    "clear_conversation": clear_conversation_fn,
    "find_coffee_shops": find_coffee_shops_fn,
    "calculate_brew_ratio": calculate_brew_ratio_fn
}

# --- Central execute_function for AI ---
def execute_function(function_name, function_args, session_id=None):
    logging.info(f"[DEBUG] execute_function called: {function_name} with args: {function_args}")
    if function_name in FUNCTION_MAP:
        try:
            if function_name == "clear_conversation" and session_id:
                return FUNCTION_MAP[function_name](session_id, **function_args)
            else:
                return FUNCTION_MAP[function_name](**function_args)
        except Exception as e:
            logging.error(f"Error executing function '{function_name}': {str(e)}")
            return {"error": f"Function '{function_name}' execution failed: {str(e)}"}
    else:
        return {"error": f"Function '{function_name}' not found"}