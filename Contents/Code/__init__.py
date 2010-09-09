import datetime, re, time, unicodedata

GOOGLE_JSON_URL = 'http://ajax.googleapis.com/ajax/services/search/web?v=1.0&rsz=large&q=%s'   #[might want to look into language/country stuff at some point] param info here: http://code.google.com/apis/ajaxsearch/documentation/reference.html
BING_JSON_URL   = 'http://api.bing.net/json.aspx?AppId=879000C53DA17EA8DB4CD1B103C00243FD0EFEE8&Version=2.2&Query=%s&Sources=web&Web.Count=8&JsonType=raw'

def Start():
  HTTP.CacheTime = CACHE_1DAY
  
class IMDBAgent(Agent.Movies):
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
    if media.guid:
      # Add a result for the id found in the passed in guid hint (likely from an .nfo file)      
      #imdbSearchHTML = str(self.httpRequest(IMDB_MOVIE_PAGE % media.guid))
      #self.scrapeIMDB_html(results, media, lang, imdbSearchHTML, scoreOverride=True, useScore=100)
      pass
          
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
            print "TITLE:", title
            titleRx = '(.*) \(([0-9]+)(/.*)?\).*'
            m = re.match(titleRx, title)
            if m:
              # Use it.
              imdbName = m.groups(1)[0]
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
      
    # Add hashing results if we need to.
    results.Sort('score', descending=True)
    if len(results) > 0:
      hiScore = results[0].score
    else:
      hiScore = 0
    
    if hiScore < 85:
      if media.openSubtitlesHash is not None and len(media.openSubtitlesHash) > 0:
        try: #just in case one of these sites is down, the whole thing doesn't fail.
          #self.addHashResult(results, media, lang, '.opensubtitles', score=85)
          #self.addHashResult(results, media, lang, '.themoviedb', score=85)
          pass
        except:
          pass
    
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

    # FAST FAIL.
    return

    page = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_PAGE % metadata.id)
    keywords = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_TAGS % metadata.id)
    cast = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_CAST % metadata.id)
    
    # Give the IMDB server a break.
    Thread.Sleep(0.25)
    
    # Build up dictionary.
    info_dict = {}
    for i in page.xpath("//div[@class='info']"):
      if i.find('h5') is not None and i.find('h5').text is not None:
        info_dict[i.find('h5').text.strip("(: ")] = i.find('div')
    
    # Title.
    (metadata.title, metadata.year) = self.getImdbName(page, None, metadata.id)
    if not metadata.title or len(metadata.title) == 0:
      raise Exception("Missing title, ignore the rest for IMDB page " + (IMDB_MOVIE_PAGE % metadata.id))
      
    metadata.title = metadata.title.strip(' "')
    
    # Studio.
    if info_dict.has_key('Company'):
      metadata.studio = info_dict["Company"].find('a').text.strip()
      
    # Rating.
    try: metadata.rating = float(self.el_text(page, '//div[@class="starbar-meta"]/b').split('/')[0])
    except: pass
      
    # Runtime.
    try:
      if info_dict.has_key('Runtime'):
        metadata.duration = int(info_dict['Runtime'].text.strip().split()[0]) * 60 * 1000
    except:
      pass
    
    # Tagline.
    taglines = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_TAGLINES % metadata.id)
    t = taglines.xpath('//div[@id="tn15content"]/p')
    if len(t) > 0:
      metadata.tagline = t[-1].text.strip() #grab the oldest tagline as the default
      if metadata.tagline[-1:] == ")":
        for i in range(-1,-1 * len(t) - 1, -1): # try to find the oldest tagline without a parenthesis at the end -- seems to avoid goofy (1985 re-release) style entries.
          if t[i].text.strip()[-1:] != ")":
            metadata.tagline = t[i].text.strip()
            break
      
    # Summary.
    if info_dict.has_key('Plot'):
      type = info_dict['Plot'].find('a')
      if type is not None and type.text.lower() != 'add synopsis':
        type = type.get('href')
        if type == 'synopsis':
          plot = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_SYNO % metadata.id)
          metadata.summary = self.el_text(plot, '//div[@id="swiki.2.1"]', True)
        else:
          plot = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_PLOT % metadata.id)
          p = plot.xpath('//p[@class="plotpar"]')
          if len(p) > 0:
            metadata.summary = p[0].text_content().strip()
            author = metadata.summary.find(' Written by')
            if author != -1:
              metadata.summary = metadata.summary[0:author].strip()
      else:
        metadata.summary = info_dict['Plot'].text.strip(' |')
      
    metadata.trivia = ""
    metadata.quotes = ""
    metadata.content_rating_age = 0
    
    if info_dict.has_key('Release Date'):
      metadata.originally_available_at = Datetime.ParseDate(info_dict["Release Date"].text.strip().split('(')[0]).date()
    
    # FIXME, how do we pick the right one?
    if info_dict.has_key('Certification'):
      certList = [a.text.strip().split(':') for a in info_dict["Certification"].xpath('a') if a.text.find('TV') == -1]
      certs = {}
      for (country, cert) in certList:
        if not certs.has_key(country):
          certs[country] = cert
      print certs
      try: metadata.content_rating = certs['USA']
      except: pass

    # Genre.
    if info_dict.has_key('Genre'):
      metadata.genres.clear()
      for genre in [a.text.strip() for a in info_dict["Genre"].xpath('a')][:-1]:
        metadata.genres.add(genre)

    # Tags.
    metadata.tags.clear()
    for tag in [a.text.strip() for a in keywords.xpath('//div[@class="keywords"]//li//a')]:
      metadata.tags.add(tag)
    
    # Cast.
    try:
      directorTable = cast.xpath("//a[@name='directors']/../../../..")[0]
      metadata.directors.clear()
      for director in directorTable.xpath('tr/td/a'):
        if director.text not in metadata.directors:
          metadata.directors.add(director.text)
    except: pass

    try:
      writerTable = cast.xpath("//a[@name='writers']/../../../..")[0]
      metadata.writers.clear()
      for writer in writerTable.xpath('tr/td/a'):
        if writer.text not in metadata.writers:
          metadata.writers.add(writer.text)
    except: pass
    
    try:
      cast = cast.xpath("//table[@class='cast']/tr")
      if len(cast) > 0:
        metadata.roles.clear()
        for member in cast:
          try:
            actor = member.xpath('td[@class="nm"]')
            character = member.xpath('td[@class="char"]')
            if len(actor) > 0 and len(character) > 0:
              href = actor[0].xpath('a')[0].get('href')
              person_id = href.split('/')[-2]
              actor_name = actor[0].text_content()
              character_name = character[0].text_content()
            
              role = metadata.roles.new()
              role.role = character_name
            
              #person = Metadata.Person(id=person_id, lang=lang)
              #person.name = actor_name
              
              headshot = member.xpath('td[@class="hs"]/a/img')
              if len(headshot) > 0:
                headshot_src = headshot[0].get('src')
                if not headshot_src[-12:] == 'no_photo.png':
                  headshot_parts = headshot_src.split('.')
                  del headshot_parts[-2]
                  headshot_url = String.Join(headshot_parts, '.')
                  headshot_name = headshot_url.split('/')[-1]
                  headshot_data = self.httpRequest(headshot_url)
                  #if headshot_name not in person.photos:
                  #  person.photos[headshot_name] = Proxy.Media(headshot_data)
                    
                  role.photo = headshot_url
              
              #role.person = person
              role.actor = actor_name
          
          except: raise
            
    except: raise
    
    # Poster.
    poster = page.xpath('//a[@name="poster"]')
    if poster:
      poster_page = self.HTMLElementFromURLWithRetries('http://www.imdb.com' + poster[0].get('href'))
      poster_img = poster_page.xpath('//img[@title=""]')
      if len(poster_img) > 0:
        path = poster_img[0].get('src')
        name = path.split('/')[-1]
        data = self.httpRequest(path)
        if name not in metadata.posters:
          metadata.posters[name] = Proxy.Media(data)
    
  def el_text(self, element, xp, extra=False):
    res = element.xpath(xp)
    if len(res) > 0:
      if extra:
        return res[0].text_content().strip()
      else:
        return res[0].text.strip()
    return None
    
  def addHashResult(self, results, media, lang, agent, score):
    movieInfo = External[agent].GetImdbIdFromHash(media.openSubtitlesHash, lang)
    if movieInfo:
      # Add a result for this show if we don't already have it.
      found = False
      for result in results:
        if result.id == movieInfo.id:
          found = True
          
      if found == False:
        # Add a result for this show
        #Log(movieInfo.id)
        imdbSearchHTML = str(self.httpRequest(IMDB_MOVIE_PAGE % movieInfo.id))
        self.scrapeIMDB_html(results, media, lang, imdbSearchHTML, scoreOverride=False)
  
  def checkAKASnames(self, id, name, mediaName):
    # Check to see if any AKAS name is a better match.
    if mediaName:
      if name[:len(mediaName)] != mediaName and name[-len(mediaName):] != mediaName: #check to make sure we are not dealing with a perfect suffix / prefix before checking aka names
        #process akas names
        imdbReleaseInfoHTML = str(self.httpRequest(IMDB_MOVIE_PAGE % id + 'releaseinfo'))
        akasHint = '<h5><a name="akas">Also Known As (AKA)</a></h5>'
        if imdbReleaseInfoHTML.count(akasHint) > 0:
          akasHTML = imdbReleaseInfoHTML.split(akasHint)[-1]
          minDist = Util.LevenshteinDistance(mediaName.lower(), name.lower())
          minSubstring = len(Util.LongestCommonSubstring(mediaName.lower(), name.lower()))
          for aka in HTML.ElementFromString(akasHTML).xpath('//table[@border="0" and @cellpadding="2"]//tr'):
            curAkaName = aka.xpath('td')[0].text
            d = Util.LevenshteinDistance(mediaName.lower(), curAkaName.lower())
            ss = len(Util.LongestCommonSubstring(mediaName.lower(), curAkaName.lower()))
            if (d * 2) < minDist and ss > minSubstring: #was: (d * 2) < minDist and ss > (minSubstring + 5):
              minDist = d
              #Log('replacing with AKA name')
              name = curAkaName
    return name.strip()    
  
  def getImdbName(self, xml, mediaName, id):
    nameH1 = xml.xpath('//h1')[0]
    
    # Whack the pro link.
    pro = nameH1.xpath('span/span[@class="pro-link"]')
    if len(pro) > 0:
      pro[0].getparent().remove(pro[0])
    
    name = xml.xpath('//h1')[0].text_content().strip()
    if name.count('(VG)') > 0:
      #is a videogame, just return the name as is so the calling function can abort
      Log("Skipping video game: [%s]" % name)
      return name  

    # Parse the name and year.
    name = re.sub('[ \n\r]+', ' ', name, re.MULTILINE)
    Log("NAME: [%s]" % name)
    m = re.match('(.*)[ ]+\(([12][0-9]{3})(/[A-Z]+)?\).*$', name)
    year = None
    if m:
      name,year = (m.group(1), m.group(2))
      year = int(year)
    
    # Check to see if any AKAS name is a better match.
    name = self.checkAKASnames(id, name, mediaName)

    # Remove quotes.
    if name[0] == '"' and name[-1] == '"':
      name = name[1:-1]

    return (name, year)
    
  def scrapeIMDB_html(self, results, media, lang, resultHTML, scoreOverride=False, useScore=None):
    pageElement = HTML.ElementFromString(resultHTML)
    id = pageElement.xpath('//link[@rel="canonical"]')[0].get('href').split('/')[-2]

    (name, year) = self.getImdbName(pageElement, media.name, id)
    
    # If Video Game don't add it.
    if name.count('(VG)') > 0:
      Log("Skipping VideoGame")
      return
    
    # Compute the distance between the two strings.
    distance = Util.LevenshteinDistance(media.name, name)
    
    if scoreOverride:
      longestCommonSub = Util.LongestCommonSubstring(media.name, name)
      #print "Longest common substring:", longestCommonSub
      if len(longestCommonSub) > 5:
        bonus = 0
      else:
        bonus = -(distance*2)
        
      #used when we are jamming stuff in from google
      if year and media.year == year:
        score = 95 + bonus
      else:
        score = 90 + bonus
    else:
      # Calculate the score - 100 = maximum
      if year and media.year == year:
       score = 100 - (distance*2)
      else:
       score = 85 - (distance*2)
    
    if useScore:
      score = useScore
    
    # Add a result for this movie.
    results.Append(
     MetadataSearchResult(
       id    = id,
       name  = name,
       year  = year,
       lang  = lang,
       score = score))
    Log('scraped results: ' + name + ' | ' + str(score))
    
  def scrapeAmazon_html(self, results, media, lang, resultHTML, scoreOverride=False):
    pageElement = HTML.ElementFromString(resultHTML)
    id = pageElement.xpath("//div[@id='imdb']//a[contains(@href,'imdb.com/title')]")[0].get('href').split('/')[-1]
    name = pageElement.xpath('//span[@id="btAsinTitle"]')[0].text
    amazonYear = int(name.split('(')[-1][:-1])
    amazonName = name.replace(' (' + str(amazonYear) + ')','').strip(' "')
    
    imdbElement = self.HTMLElementFromURLWithRetries(IMDB_MOVIE_PAGE % id)
    (imdbName, imdbYear) = self.getImdbName(imdbElement, media.name)
    
    # Sanity check amazon<-->imdb link...sometimes amazon is *way* off on their imdb links
    distance = Util.LevenshteinDistance(amazonName.lower(), imdbName.lower())
    if amazonYear == imdbYear:
      amzScore = 100 - (distance*2)
    else:
      amzScore = 85 - (distance*2)
    Log("amzScore: " + str(amzScore))
    
    if amzScore > 70:
      #passed sanity check
      if scoreOverride:
        #used when we are jamming stuff in from google
        if year and media.year == year:
          score = 95
        else:
          score = 85
      else:
        # Calculate the score - 100 = maximum
        distance = Util.LevenshteinDistance(media.name.lower(), name.lower())
        if year and media.year == year:
         score = 100 - (distance*2)
        else:
         score = 85 - (distance*2)

      # Add a result for this show
      results.Append(
       MetadataSearchResult(
         id    = id,
         name  = name,
         year  = year,
         lang  = lang,
         score = score))
      Log('scraped results: ' + name + ' | year = ' + str(year) + ' | score = ' + str(score))
      
