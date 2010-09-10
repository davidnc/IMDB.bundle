import datetime, re, time, unicodedata

GOOGLE_JSON_URL = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&rsz=large&q=%s'   #[might want to look into language/country stuff at some point] param info here: http://code.google.com/apis/ajaxsearch/documentation/reference.html
BING_JSON_URL   = 'http://api.bing.net/json.aspx?AppId=879000C53DA17EA8DB4CD1B103C00243FD0EFEE8&Version=2.2&Query=%s&Sources=web&Web.Count=8&JsonType=raw'

def Start():
  HTTP.CacheTime = CACHE_1DAY
  
class PlexMovieAgent(Agent.Movies):
  name = 'Plex'
  languages = [Locale.Language.English]
  
  def httpRequest(self, url):
    time.sleep(1)
    res = None
    for i in range(5):
      try: 
        res = HTTP.Request(url, headers = {'User-agent': UserAgent})
      except: 
        Log("Error hitting HTTP url:", url)
        time.sleep(1)
        
    return res
    
  def HTMLElementFromURLWithRetries(self, url):
    res = self.httpRequest(url)
    if res:
      return HTML.ElementFromString(res)
    return None
  
  def search(self, results, media, lang):
    
    # See if we're being passed the ID.
    #if media.guid:
      # Add a result for the id found in the passed in guid hint (likely from an .nfo file)      
      #imdbSearchHTML = str(self.httpRequest(IMDB_MOVIE_PAGE % media.guid))
      #self.scrapeIMDB_html(results, media, lang, imdbSearchHTML, scoreOverride=True, useScore=100)
    #pass
          
    if media.year:
      searchYear = ' (' + str(media.year) + ')'
    else:
      searchYear = ''
    
    normalizedName = String.StripDiacritics(media.name)
    GOOGLE_JSON_QUOTES = GOOGLE_JSON_URL % String.Quote('"' + normalizedName + searchYear + '"', usePlus=True) + '+site:imdb.com'
    GOOGLE_JSON_NOQUOTES = GOOGLE_JSON_URL % String.Quote(normalizedName + searchYear, usePlus=True) + '+site:imdb.com'
    GOOGLE_JSON_NOSITE = GOOGLE_JSON_URL % String.Quote(normalizedName + searchYear, usePlus=True) + '+imdb.com'
    BING_JSON = BING_JSON_URL % String.Quote(normalizedName + searchYear, usePlus=True) + '+site:imdb.com'
    
    subsequentSearchPenalty = 0
    idMap = {}
    
    for s in [GOOGLE_JSON_QUOTES, GOOGLE_JSON_NOQUOTES, GOOGLE_JSON_NOSITE, BING_JSON]:
      if s == GOOGLE_JSON_QUOTES and (media.name.count(' ') == 0 or media.name.count('&') > 0 or media.name.count(' and ') > 0): # no reason to run this test, plus it screwed up some searches
        continue 
        
      subsequentSearchPenalty += 1

       # Check to see if we need to bother running the subsequent searches
      if len(results) <= 3:
        score = 99
        
        # Make sure we have results and normalize them.
        hasResults = False
        try:
          if s.count('bing.net') > 0:
            jsonObj = JSON.ObjectFromURL(s, cacheTime=CACHE_1DAY)['SearchResponse']['Web']
            if jsonObj['Total'] > 0:
              jsonObj = jsonObj['Results']
              hasResults = True
              urlKey = 'Url'
              titleKey = 'Title'
          elif s.count('googleapis.com') > 0:
            jsonObj = JSON.ObjectFromURL(s)
            if jsonObj['responseData'] != None:
              jsonObj = jsonObj['responseData']['results']
              if len(jsonObj) > 0:
                hasResults = True
                urlKey = 'unescapedUrl'
                titleKey = 'titleNoFormatting'
        except:
          Log("Exception processing search engine results.")
          pass
          
        # Now walk through the results.    
        if hasResults:
          for r in jsonObj:
            
            # Get data.
            url = r[urlKey]
            title = r[titleKey]

            # Parse out title, year, and extra.
            titleRx = '(.*) \(([0-9]+)(/.*)?\).*'
            m = re.match(titleRx, title)
            if m:
              # A bit more processing for the name.
              imdbName = m.groups(1)[0]
              imdbName = re.sub('^[iI][mM][dD][bB][ ]*:[ ]*', '', imdbName)
              
              imdbYear = int(m.groups(1)[1])
            else:
              # Doesn't match, let's skip it.
              Log("Skipping strange title: " + title)
              continue
              
            scorePenalty = 0
            url = r[urlKey].lower().replace('us.vdc','www').replace('title?','title/tt') #massage some of the weird url's google has
            if url[-1:] == '/':
              url = url[:-1]
      
            splitUrl = url.split('/')
      
            if len(splitUrl) == 6 and splitUrl[-2].startswith('tt'):
              
              # This is the case where it is not just a link to the main imdb title page, but to a subpage. 
              # In some odd cases, google is a bit off so let's include these with lower scores "just in case".
              #
              scorePenalty = 10
              del splitUrl[-1]
      
            if len(splitUrl) > 5 and splitUrl[-1].startswith('tt'):
              while len(splitUrl) > 5:
                del splitUrl[-2]
              scorePenalty += 5

            if len(splitUrl) == 5 and splitUrl[-1].startswith('tt'):
              id = splitUrl[-1]
              if id.count('+') > 0:
                # Penalizing for abnormal tt link.
                scorePenalty += 10
              try:
                # Don't process for the same ID more than once.
                if idMap.has_key(id):
                  continue
                  
                idMap[id] = True
                
                # Check to see if the item's release year is in the future, if so penalize.
                if imdbYear > datetime.datetime.now().year:
                  Log(imdbName + ' penalizing for future release date')
                  scorePenalty += 25
              
                # Check to see if the hinted year is different from imdb's year, if so penalize.
                elif media.year and int(media.year) != int(imdbYear): 
                  Log(imdbName + ' penalizing for hint year and imdb year being different')
                  yearDiff = abs(int(media.year)-(int(imdbYear)))
                  if yearDiff == 1:
                    scorePenalty += 5
                  elif yearDiff == 2:
                    scorePenalty += 10
                  else:
                    scorePenalty += 15
                    
                # Bonus (or negatively penalize) for year match.
                elif media.year and int(media.year) != int(imdbYear): 
                  scorePenalty += -5
                
                # It's a video game, run away!
                if title.count('(VG)') > 0:
                  break
                  
                # It's a TV series, don't use it.
                if title.count('(TV series)') > 0:
                  Log(imdbName + ' penalizing for TV series')
                  scorePenalty += 6
              
                # Sanity check to make sure we have SOME common substring.
                longestCommonSubstring = len(Util.LongestCommonSubstring(media.name.lower(), imdbName.lower()))
                
                # If we don't have at least 10% in common, then penalize below the 80 point threshold
                if (float(longestCommonSubstring) / len(media.name)) < .15: 
                  scorePenalty += 25
                
                # Finally, add the result.
                results.Append( MetadataSearchResult(id = id, name  = imdbName, year = imdbYear, lang  = lang, score = score - (scorePenalty + subsequentSearchPenalty)) )
              except:
                Log('Exception processing IMDB Result')
                pass
           
            # Each search entry is worth less, but we subtract even if we don't use the entry...might need some thought.
            score = score - 4 
      
    results.Sort('score', descending=True)
    
    # Finally, de-dupe the results.
    toWhack = []
    resultMap = {}
    for result in results:
      if not resultMap.has_key(result.id):
        resultMap[result.id] = True
      else:
        toWhack.append(result)
        
    for dupe in toWhack:
      results.Remove(dupe)
      
  def update(self, metadata, media, lang):
    
    pass

    #metadata.studio = info_dict["Company"].find('a').text.strip()
    #metadata.rating = float(self.el_text(page, '//div[@class="starbar-meta"]/b').split('/')[0])
    #metadata.duration = int(info_dict['Runtime'].text.strip().split()[0]) * 60 * 1000
    #metadata.tagline = t[i].text.strip()
    #metadata.summary = info_dict['Plot'].text.strip(' |')
    #metadata.trivia = ""
    #metadata.quotes = ""
    #metadata.content_rating_age = 0
    #metadata.originally_available_at = Datetime.ParseDate(info_dict["Release Date"].text.strip().split('(')[0]).date()
    #metadata.content_rating = certs['USA']
    #metadata.genres.add(genre)
    #metadata.tags.add(tag)
    #metadata.directors.add(director.text)
    #metadata.writers.add(writer.text)
    
    #metadata.roles.clear()
    #for member in cast:
    #    role = metadata.roles.new()
    #    role.role = character_name
    #    role.photo = headshot_url
    #     role.actor = actor_name
          
    # Poster.
    #data = self.httpRequest(path)
    #if name not in metadata.posters:
    #  metadata.posters[name] = Proxy.Media(data)
  